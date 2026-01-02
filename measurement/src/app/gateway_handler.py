"""Gateway handler for receiving forwarded events from the gateway service.

This module handles stateless computation events forwarded from the gateway.
All session management has been moved to the lobby service.

Stateless events handled here:
- measurement.create_job: Create a new job for storing measurement data
- measurement.get_job: Retrieve job data
- measurement.get_audio_info: Get measurement audio timing info
- analysis.run: Run audio analysis on uploaded recordings
"""
from __future__ import annotations

import logging
import pathlib
import uuid
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.analysis.alignment import extract_sweep_for_deconvolution, AlignmentResult
from app.analysis.audio_generator import MeasurementSignalConfig
from app.analysis.io import normalize_peak, read_audio_mono
from app.analysis.metrics import (
    build_display_metrics,
    clarity_definition_metrics,
    deconvolve_sweep,
    drr_metrics,
    freq_response_summary,
    rt_metrics_from_ir,
    snr_quality,
)
from app.analysis.sti import sti_from_impulse_response
from app.models import MapModel
from app.reference_store import reference_store
from app.settings import settings
from app.storage import LocalJobStore


logger = logging.getLogger(__name__)


class GatewayClientInfo(BaseModel):
    """Client information forwarded from the gateway."""
    device_id: str
    connection_id: str
    ip: str | None = None


class ClientMessage(BaseModel):
    """Message structure from the client via gateway."""
    event: str = Field(min_length=1)
    request_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class GatewayForwardRequest(BaseModel):
    """Request body sent by the gateway to forward client events."""
    client: GatewayClientInfo
    message: ClientMessage


router = APIRouter()

# Initialize store
store = LocalJobStore(root_dir=pathlib.Path(settings.data_dir))


def _handle_measurement_create_job(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Handle measurement.create_job event."""
    # Note: map_data can be an empty dict {} if room plan hasn't been shared yet
    map_data = data.get("map")
    meta = data.get("meta", {})
    
    if map_data is None:
        raise HTTPException(status_code=400, detail="Missing 'map' in data")
    
    try:
        map_model = MapModel.model_validate(map_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid map data: {e}")
    
    job_id = str(uuid.uuid4())
    job_dir = store.ensure_job(job_id)
    store.write_json(job_dir / "map.json", map_model.model_dump(mode="json"))
    store.write_json(job_dir / "job_meta.json", {**meta, "device_id": client.device_id})
    
    logger.info(f"Created job {job_id} for device {client.device_id}")
    
    return {"job_id": job_id}


def _handle_measurement_get_job(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Handle measurement.get_job event."""
    job_id = data.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing 'job_id' in data")
    
    job_dir = store.ensure_job(job_id)
    payload = {
        "job_id": job_id,
        "map": store.read_json(job_dir / "map.json"),
        "meta": store.read_json(job_dir / "job_meta.json"),
        "uploads": sorted([p.name for p in (job_dir / "uploads").glob("*") if p.is_file()]),
    }
    
    results_path = job_dir / "results" / "analysis.json"
    if results_path.exists():
        payload["results"] = store.read_json(results_path)
    
    return payload


def _handle_analysis_run(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Handle analysis.run event."""
    job_id = data.get("job_id")
    source = data.get("source")
    
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing 'job_id' in data")
    if not source:
        raise HTTPException(status_code=400, detail="Missing 'source' in data")
    
    job_dir = store.ensure_job(job_id)
    uploads_dir = job_dir / "uploads"
    
    if source == "impulse_response":
        name = data.get("impulse_response_upload", "impulse_response")
        ir_path = uploads_dir / name
        if not ir_path.exists():
            raise HTTPException(status_code=400, detail=f"Missing upload '{name}'")
        
        ir, fs = read_audio_mono(str(ir_path))
        ir = normalize_peak(ir)
    
    elif source == "sweep_deconvolution":
        rec_name = data.get("recording_upload", "recording")
        sweep_name = data.get("sweep_reference_upload", "sweep_reference")
        rec_path = uploads_dir / rec_name
        sweep_path = uploads_dir / sweep_name
        
        if not rec_path.exists() or not sweep_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Missing uploads '{rec_name}' and/or '{sweep_name}'"
            )
        
        rec, fs_r = read_audio_mono(str(rec_path))
        sweep, fs_s = read_audio_mono(str(sweep_path))
        
        if fs_r != fs_s:
            raise HTTPException(
                status_code=400,
                detail=f"Samplerate mismatch recording={fs_r} sweep={fs_s}"
            )
        
        ir = deconvolve_sweep(rec, sweep)
        ir = normalize_peak(ir)
        fs = fs_r
    
    elif source == "sweep_deconvolution_generated":
        # Use recording and the stored sweep signal for deconvolution
        # Requires audio_hash to look up the exact signals used during measurement
        rec_name = data.get("recording_upload", "recording")
        audio_hash = data.get("audio_hash")  # Required: hash of measurement audio
        rec_path = uploads_dir / rec_name
        
        if not rec_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Missing upload '{rec_name}'"
            )
        
        if not audio_hash:
            raise HTTPException(
                status_code=400,
                detail="Missing 'audio_hash' - required to retrieve the exact measurement signals used"
            )
        
        rec, fs_r = read_audio_mono(str(rec_path))
        
        # Load stored references - these MUST exist
        logger.info(f"Loading stored references for audio_hash={audio_hash[:16]}...")
        
        chirp_result = reference_store.load_chirp(audio_hash)
        sweep_result = reference_store.load_sweep(audio_hash)
        
        if not chirp_result or not sweep_result:
            raise HTTPException(
                status_code=400,
                detail=f"No stored reference signals found for audio_hash={audio_hash[:16]}... "
                       "The measurement audio must be generated via GET /v1/measurement/audio first."
            )
        
        chirp_loaded, chirp_sr = chirp_result
        sweep_loaded, sweep_sr = sweep_result
        
        # Verify sample rates match
        if chirp_sr != fs_r or sweep_sr != fs_r:
            raise HTTPException(
                status_code=400,
                detail=f"Sample rate mismatch: recording={fs_r}Hz, stored_chirp={chirp_sr}Hz, "
                       f"stored_sweep={sweep_sr}Hz. Recording must have same sample rate as measurement audio."
            )
        
        logger.info(
            f"Using stored reference signals (chirp={len(chirp_loaded)}, sweep={len(sweep_loaded)})"
        )
        
        # Create config for alignment (we need timing info)
        config = MeasurementSignalConfig(sample_rate=fs_r)
        
        # === CHIRP ALIGNMENT ===
        # Detect sync chirps and extract the aligned sweep portion from recording
        aligned_rec, alignment_result = extract_sweep_for_deconvolution(
            recording=rec,
            sample_rate=fs_r,
            config=config,
            chirp_template=chirp_loaded,
        )
        
        logger.info(
            f"Alignment result: success={alignment_result.success}, "
            f"start_chirp_detected={alignment_result.start_chirp.detected if alignment_result.start_chirp else False}, "
            f"aligned_length={len(aligned_rec)} samples ({len(aligned_rec)/fs_r:.2f}s)"
        )
        
        # Save debug audio files
        debug_dir = pathlib.Path(settings.debug_dir)
        debug_dir.mkdir(parents=True, exist_ok=True)
        
        # Save original recording
        original_debug_path = debug_dir / f"original_{job_id}.wav"
        sf.write(str(original_debug_path), rec, fs_r, subtype='PCM_16')
        logger.info(f"Saved original recording to {original_debug_path}")
        
        # Save aligned recording
        aligned_debug_path = debug_dir / f"aligned_{job_id}.wav"
        sf.write(str(aligned_debug_path), aligned_rec, fs_r, subtype='PCM_16')
        logger.info(f"Saved aligned recording to {aligned_debug_path}")
        
        # Save chirp template
        chirp_debug_path = debug_dir / f"chirp_template_{job_id}.wav"
        sf.write(str(chirp_debug_path), chirp_loaded, fs_r, subtype='PCM_16')
        logger.info(f"Saved chirp template to {chirp_debug_path}")
        
        # Save sweep reference
        sweep_debug_path = debug_dir / f"sweep_reference_{job_id}.wav"
        sf.write(str(sweep_debug_path), sweep_loaded, fs_r, subtype='PCM_16')
        logger.info(f"Saved sweep reference to {sweep_debug_path}")
        
        # Deconvolve using ALIGNED recording and stored sweep
        ir = deconvolve_sweep(aligned_rec, sweep_loaded)
        ir = normalize_peak(ir)
        fs = fs_r
        
        # Save impulse response
        ir_debug_path = debug_dir / f"impulse_response_{job_id}.wav"
        sf.write(str(ir_debug_path), ir.astype(np.float32), fs_r, subtype='FLOAT')
        logger.info(f"Saved impulse response to {ir_debug_path}")
        
        # Save alignment metadata
        alignment_meta = {
            "success": alignment_result.success,
            "message": alignment_result.message,
            "original_length_samples": alignment_result.original_length_samples,
            "aligned_length_samples": alignment_result.aligned_length_samples,
            "sweep_start_sample": alignment_result.sweep_start_sample,
            "sweep_end_sample": alignment_result.sweep_end_sample,
            "audio_hash": audio_hash,
            "start_chirp": {
                "detected": alignment_result.start_chirp.detected,
                "sample_index": alignment_result.start_chirp.sample_index,
                "time_seconds": alignment_result.start_chirp.time_seconds,
                "correlation_peak": alignment_result.start_chirp.correlation_peak,
                "confidence": alignment_result.start_chirp.confidence,
            } if alignment_result.start_chirp else None,
            "end_chirp": {
                "detected": alignment_result.end_chirp.detected,
                "sample_index": alignment_result.end_chirp.sample_index,
                "time_seconds": alignment_result.end_chirp.time_seconds,
                "correlation_peak": alignment_result.end_chirp.correlation_peak,
                "confidence": alignment_result.end_chirp.confidence,
            } if alignment_result.end_chirp else None,
        }
        store.write_json(job_dir / "results" / "alignment.json", alignment_meta)
        
        logger.info(
            f"Deconvolved with alignment (fs={fs_r}, "
            f"sweep_len={len(sweep_loaded)}, aligned_rec_len={len(aligned_rec)})"
        )
    
    else:
        raise HTTPException(status_code=400, detail="Invalid source")
    
    rt = rt_metrics_from_ir(ir, fs)
    clarity = clarity_definition_metrics(ir, fs)
    drr = drr_metrics(ir, fs)
    quality = snr_quality(ir)
    sti = sti_from_impulse_response(ir, fs)
    
    results = {
        "samplerate_hz": fs,
        "rt": rt,
        "clarity": clarity,
        "drr": drr,
        "quality": quality,
        "frequency_response": freq_response_summary(ir, fs),
        "sti": sti,
        # Universal display format - frontend renders this dynamically
        "display_metrics": build_display_metrics(
            rt=rt,
            clarity=clarity,
            drr=drr,
            quality=quality,
            sti=sti,
        ),
    }
    
    store.write_json(job_dir / "results" / "analysis.json", results)
    
    logger.info(f"Analysis complete for job {job_id}")
    
    return {"job_id": job_id, "results": results}


def _handle_measurement_get_audio_info(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.get_audio_info event.
    
    Returns timing information about the measurement audio signal.
    """
    sample_rate = data.get("sample_rate", 48000)
    config = MeasurementSignalConfig(sample_rate=sample_rate)
    return get_signal_timing(config)


# Event handlers mapping - all stateless computation events
EVENT_HANDLERS = {
    "measurement.create_job": _handle_measurement_create_job,
    "measurement.get_job": _handle_measurement_get_job,
    "measurement.get_audio_info": _handle_measurement_get_audio_info,
    "analysis.run": _handle_analysis_run,
}


@router.post("/gateway/handle")
def gateway_handle(request: GatewayForwardRequest) -> dict[str, Any]:
    """
    Handle forwarded events from the gateway.
    
    This endpoint receives stateless computation events that clients send via
    WebSocket to the gateway, which then forwards them here for processing.
    
    All session management events are now handled by the lobby service.
    """
    event = request.message.event
    
    handler = EVENT_HANDLERS.get(event)
    if handler is None:
        logger.warning(f"Unknown event received: {event}")
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event: {event}"
        )
    
    logger.info(
        f"Gateway event '{event}' received (request_id={request.message.request_id}, "
        f"device={request.client.device_id})"
    )
    
    try:
        result = handler(request.client, request.message.data)
        logger.debug(f"Gateway event '{event}' succeeded")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Exception in handler for {event}")
        raise HTTPException(status_code=500, detail=str(e))
