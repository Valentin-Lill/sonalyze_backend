"""Gateway handler for receiving forwarded events from the gateway service."""
from __future__ import annotations

import asyncio
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
from app.coordinator import (
    cancel_session,
    client_ready,
    create_session,
    get_session_status,
    recording_uploaded,
    speaker_finished,
    start_next_speaker_measurement,
)
from app.models import MapModel
from app.settings import settings
from app.storage import LocalJobStore


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
    
    return {"job_id": job_id, "results": results}


# =============================================================================
# Measurement Session Coordination Handlers
# =============================================================================

async def _handle_measurement_create_session(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.create_session event.
    
    Creates a new measurement session for coordinated speaker/microphone recordings.
    Expected data:
    - job_id: Associated job ID
    - lobby_id: Lobby ID for participant management
    - speakers: List of {device_id, slot_id, slot_label?}
    - microphones: List of {device_id, slot_id, slot_label?}
    """
    job_id = data.get("job_id")
    lobby_id = data.get("lobby_id")
    speakers = data.get("speakers", [])
    microphones = data.get("microphones", [])
    
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing 'job_id' in data")
    if not lobby_id:
        raise HTTPException(status_code=400, detail="Missing 'lobby_id' in data")
    if not speakers:
        raise HTTPException(status_code=400, detail="At least one speaker is required")
    if not microphones:
        raise HTTPException(status_code=400, detail="At least one microphone is required")
    
    # Validate speaker and microphone data
    for i, s in enumerate(speakers):
        if "device_id" not in s or "slot_id" not in s:
            raise HTTPException(
                status_code=400,
                detail=f"Speaker {i} missing 'device_id' or 'slot_id'"
            )
    
    for i, m in enumerate(microphones):
        if "device_id" not in m or "slot_id" not in m:
            raise HTTPException(
                status_code=400,
                detail=f"Microphone {i} missing 'device_id' or 'slot_id'"
            )
    
    session = await create_session(
        job_id=job_id,
        lobby_id=lobby_id,
        speakers=speakers,
        microphones=microphones,
    )
    
    # Get audio timing info
    timing = get_signal_timing(MeasurementSignalConfig())
    
    return {
        "session_id": session.session_id,
        "job_id": job_id,
        "lobby_id": lobby_id,
        "total_speakers": len(speakers),
        "total_microphones": len(microphones),
        "audio_duration_seconds": timing["total_duration"],
        "audio_info_endpoint": "/v1/measurement/audio/info",
    }


async def _handle_measurement_start_speaker(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.start_speaker event.
    
    Starts the measurement cycle for the next speaker.
    This will notify all clients to prepare.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    try:
        return await start_next_speaker_measurement(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_client_ready(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.client_ready event.
    
    Called by speakers and microphones when they are ready.
    When all clients are ready, playback is triggered.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    try:
        return await client_ready(session_id, client.device_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_speaker_finished(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.speaker_finished event.
    
    Called by the speaker when audio playback is complete.
    This signals microphones to stop recording and upload.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    try:
        return await speaker_finished(session_id, client.device_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_recording_uploaded(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.recording_uploaded event.
    
    Called by microphones when their recording has been uploaded.
    When all recordings are uploaded, the next speaker is triggered.
    """
    session_id = data.get("session_id")
    upload_name = data.get("upload_name")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    if not upload_name:
        raise HTTPException(status_code=400, detail="Missing 'upload_name' in data")
    
    try:
        return await recording_uploaded(session_id, client.device_id, upload_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_session_status(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.session_status event.
    
    Returns the current status of a measurement session.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    try:
        return await get_session_status(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


async def _handle_measurement_cancel_session(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.cancel_session event.
    
    Cancels an ongoing measurement session.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    try:
        return await cancel_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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


# Event handlers mapping - sync handlers
SYNC_EVENT_HANDLERS = {
    "measurement.create_job": _handle_measurement_create_job,
    "measurement.get_job": _handle_measurement_get_job,
    "analysis.run": _handle_analysis_run,
    "measurement.get_audio_info": _handle_measurement_get_audio_info,
}

# Event handlers mapping - async handlers (for coordinator)
ASYNC_EVENT_HANDLERS = {
    "measurement.create_session": _handle_measurement_create_session,
    "measurement.start_speaker": _handle_measurement_start_speaker,
    "measurement.client_ready": _handle_measurement_client_ready,
    "measurement.speaker_finished": _handle_measurement_speaker_finished,
    "measurement.recording_uploaded": _handle_measurement_recording_uploaded,
    "measurement.session_status": _handle_measurement_session_status,
    "measurement.cancel_session": _handle_measurement_cancel_session,
}


@router.post("/gateway/handle")
async def gateway_handle(request: GatewayForwardRequest) -> dict[str, Any]:
    """
    Handle forwarded events from the gateway.
    
    This endpoint receives events that clients send via WebSocket to the gateway,
    which then forwards them here for processing.
    """
    event = request.message.event
    print(f"[gateway_handler] Received event: {event}")
    print(f"[gateway_handler] Client: device_id={request.client.device_id}, connection_id={request.client.connection_id}")
    print(f"[gateway_handler] Message data: {request.message.data}")
    
    # Check sync handlers first
    sync_handler = SYNC_EVENT_HANDLERS.get(event)
    if sync_handler is not None:
        print(f"[gateway_handler] Using sync handler for {event}")
        try:
            result = sync_handler(request.client, request.message.data)
            print(f"[gateway_handler] Sync handler success: {result}")
            return result
        except HTTPException as e:
            print(f"[gateway_handler] HTTPException in sync handler: {e.status_code} - {e.detail}")
            raise
        except Exception as e:
            print(f"[gateway_handler] Exception in sync handler: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # Check async handlers
    async_handler = ASYNC_EVENT_HANDLERS.get(event)
    if async_handler is not None:
        print(f"[gateway_handler] Using async handler for {event}")
        try:
            result = await async_handler(request.client, request.message.data)
            print(f"[gateway_handler] Async handler success: {result}")
            return result
        except HTTPException as e:
            print(f"[gateway_handler] HTTPException in async handler: {e.status_code} - {e.detail}")
            raise
        except Exception as e:
            print(f"[gateway_handler] Exception in async handler: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    print(f"[gateway_handler] Unknown event: {event}")
    raise HTTPException(
        status_code=400,
        detail=f"Unknown event: {event}"
    )
