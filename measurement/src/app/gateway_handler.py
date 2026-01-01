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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.analysis.audio_generator import MeasurementSignalConfig, get_signal_timing
from app.analysis.io import normalize_peak, read_audio_mono
from app.analysis.metrics import (
    clarity_definition_metrics,
    deconvolve_sweep,
    drr_metrics,
    freq_response_summary,
    rt_metrics_from_ir,
    snr_quality,
)
from app.analysis.sti import sti_from_impulse_response
from app.models import MapModel
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
    
    else:
        raise HTTPException(status_code=400, detail="Invalid source")
    
    results = {
        "samplerate_hz": fs,
        "rt": rt_metrics_from_ir(ir, fs),
        "clarity": clarity_definition_metrics(ir, fs),
        "drr": drr_metrics(ir, fs),
        "quality": snr_quality(ir),
        "frequency_response": freq_response_summary(ir, fs),
        "sti": sti_from_impulse_response(ir, fs),
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
