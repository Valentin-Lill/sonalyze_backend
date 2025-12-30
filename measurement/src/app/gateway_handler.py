"""Gateway handler for receiving forwarded events from the gateway service.

This module handles WebSocket events forwarded from the gateway, implementing
the 11-step measurement protocol for coordinated speaker/microphone recordings.

Protocol Steps:
1. Admin initializes measurement from the measurement page
2. Backend sends "measurement.start_measurement" to all speakers/microphones  
3. Each client sends "measurement.ready" when prepared
4. When all ready, backend sends "measurement.request_audio" to speaker
5. Speaker downloads audio and sends "measurement.speaker_audio_ready"
6. Backend sends "measurement.start_recording" to all microphones
7. Each microphone sends "measurement.recording_started" when recording
8. When all recording, backend sends "measurement.start_playback" to speaker
9. Speaker plays audio and sends "measurement.playback_complete"
10. Backend sends "measurement.stop_recording" to all microphones
11. Each microphone uploads and sends "measurement.recording_uploaded"
"""
from __future__ import annotations

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
    handle_error,
    playback_complete,
    recording_started,
    recording_uploaded,
    speaker_audio_ready,
    start_measurement,
    start_next_speaker_measurement,
)
from app.measurement_logger import log
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
    Handle measurement.create_session event (Step 1).
    
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
    
    log.info(
        f"Creating measurement session",
        component="gateway",
        device_id=client.device_id,
        data={"job_id": job_id, "lobby_id": lobby_id, "speakers": len(speakers), "microphones": len(microphones)},
    )
    
    if not job_id:
        log.error("Missing 'job_id' in create_session", component="gateway", device_id=client.device_id)
        raise HTTPException(status_code=400, detail="Missing 'job_id' in data")
    if not lobby_id:
        log.error("Missing 'lobby_id' in create_session", component="gateway", device_id=client.device_id)
        raise HTTPException(status_code=400, detail="Missing 'lobby_id' in data")
    if not speakers:
        log.error("No speakers in create_session", component="gateway", device_id=client.device_id)
        raise HTTPException(status_code=400, detail="At least one speaker is required")
    if not microphones:
        log.error("No microphones in create_session", component="gateway", device_id=client.device_id)
        raise HTTPException(status_code=400, detail="At least one microphone is required")
    
    # Validate speaker and microphone data
    for i, s in enumerate(speakers):
        if "device_id" not in s or "slot_id" not in s:
            log.error(f"Speaker {i} missing device_id or slot_id", component="gateway", device_id=client.device_id)
            raise HTTPException(
                status_code=400,
                detail=f"Speaker {i} missing 'device_id' or 'slot_id'"
            )
    
    for i, m in enumerate(microphones):
        if "device_id" not in m or "slot_id" not in m:
            log.error(f"Microphone {i} missing device_id or slot_id", component="gateway", device_id=client.device_id)
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
    
    log.log_step(
        1, "Session Created Successfully",
        session_id=session.session_id,
        data={"total_speakers": len(speakers), "total_microphones": len(microphones)},
    )
    
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
    Handle measurement.start_speaker event (Step 2).
    
    Starts the measurement cycle for the next speaker.
    This will notify all clients via "measurement.start_measurement".
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    log.log_event_received(
        "measurement.start_speaker",
        device_id=client.device_id,
        session_id=session_id,
    )
    
    try:
        return await start_measurement(session_id)
    except ValueError as e:
        log.error(f"Start speaker failed: {e}", component="gateway", session_id=session_id)
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_client_ready(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.ready event (Step 3).
    
    Called by speakers and microphones when they are ready.
    When all clients are ready, audio is requested from the speaker.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    log.log_event_received(
        "measurement.ready",
        device_id=client.device_id,
        session_id=session_id,
    )
    
    try:
        return await client_ready(session_id, client.device_id)
    except ValueError as e:
        log.error(f"Client ready failed: {e}", component="gateway", session_id=session_id, device_id=client.device_id)
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_speaker_audio_ready(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.speaker_audio_ready event (Step 5).
    
    Called by the speaker when audio is downloaded and ready.
    This triggers all microphones to start recording.
    """
    session_id = data.get("session_id")
    audio_hash = data.get("audio_hash")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    log.log_event_received(
        "measurement.speaker_audio_ready",
        device_id=client.device_id,
        session_id=session_id,
        data={"audio_hash": audio_hash},
    )
    
    try:
        return await speaker_audio_ready(session_id, client.device_id, audio_hash)
    except ValueError as e:
        log.error(f"Speaker audio ready failed: {e}", component="gateway", session_id=session_id, device_id=client.device_id)
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_recording_started(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.recording_started event (Step 7).
    
    Called by microphones when they have started recording.
    When all microphones are recording, playback is triggered.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    log.log_event_received(
        "measurement.recording_started",
        device_id=client.device_id,
        session_id=session_id,
    )
    
    try:
        return await recording_started(session_id, client.device_id)
    except ValueError as e:
        log.error(f"Recording started failed: {e}", component="gateway", session_id=session_id, device_id=client.device_id)
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_playback_complete(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.playback_complete event (Step 9).
    
    Called by the speaker when audio playback is complete.
    This signals microphones to stop recording and upload.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    log.log_event_received(
        "measurement.playback_complete",
        device_id=client.device_id,
        session_id=session_id,
    )
    
    try:
        return await playback_complete(session_id, client.device_id)
    except ValueError as e:
        log.error(f"Playback complete failed: {e}", component="gateway", session_id=session_id, device_id=client.device_id)
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_speaker_finished(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.speaker_finished event (LEGACY - redirects to playback_complete).
    
    DEPRECATED: Use measurement.playback_complete instead.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    log.warning(
        "measurement.speaker_finished is deprecated, use measurement.playback_complete",
        component="gateway",
        session_id=session_id,
        device_id=client.device_id,
    )
    
    try:
        return await playback_complete(session_id, client.device_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_recording_uploaded(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.recording_uploaded event (Step 11).
    
    Called by microphones when their recording has been uploaded.
    When all recordings are uploaded, the next speaker is triggered.
    """
    session_id = data.get("session_id")
    upload_name = data.get("upload_name")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    if not upload_name:
        raise HTTPException(status_code=400, detail="Missing 'upload_name' in data")
    
    log.log_event_received(
        "measurement.recording_uploaded",
        device_id=client.device_id,
        session_id=session_id,
        data={"upload_name": upload_name},
    )
    
    try:
        return await recording_uploaded(session_id, client.device_id, upload_name)
    except ValueError as e:
        log.error(f"Recording uploaded failed: {e}", component="gateway", session_id=session_id, device_id=client.device_id)
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_error(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Handle measurement.error event.
    
    Called by any client when an error occurs during measurement.
    This may cancel the current measurement depending on severity.
    """
    session_id = data.get("session_id")
    error_message = data.get("error_message", "Unknown error")
    error_code = data.get("error_code")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    log.log_event_received(
        "measurement.error",
        device_id=client.device_id,
        session_id=session_id,
        data={"error_message": error_message, "error_code": error_code},
    )
    
    try:
        return await handle_error(session_id, client.device_id, error_message, error_code)
    except ValueError as e:
        log.error(f"Handle error failed: {e}", component="gateway", session_id=session_id, device_id=client.device_id)
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
    
    log.log_event_received(
        "measurement.session_status",
        device_id=client.device_id,
        session_id=session_id,
    )
    
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
    reason = data.get("reason", "cancelled_by_client")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    log.log_event_received(
        "measurement.cancel_session",
        device_id=client.device_id,
        session_id=session_id,
        data={"reason": reason},
    )
    
    try:
        return await cancel_session(session_id, reason)
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
# Supports both new 11-step protocol and legacy events
ASYNC_EVENT_HANDLERS = {
    # Session management
    "measurement.create_session": _handle_measurement_create_session,
    "measurement.start_speaker": _handle_measurement_start_speaker,
    "measurement.session_status": _handle_measurement_session_status,
    "measurement.cancel_session": _handle_measurement_cancel_session,
    
    # New 11-step protocol events
    "measurement.ready": _handle_measurement_client_ready,  # Step 3
    "measurement.speaker_audio_ready": _handle_measurement_speaker_audio_ready,  # Step 5
    "measurement.recording_started": _handle_measurement_recording_started,  # Step 7
    "measurement.playback_complete": _handle_measurement_playback_complete,  # Step 9
    "measurement.recording_uploaded": _handle_measurement_recording_uploaded,  # Step 11
    "measurement.error": _handle_measurement_error,  # Error handling
    
    # Legacy event aliases (for backward compatibility)
    "measurement.client_ready": _handle_measurement_client_ready,  # Alias for measurement.ready
    "measurement.speaker_finished": _handle_measurement_speaker_finished,  # Alias for playback_complete
}


@router.post("/gateway/handle")
async def gateway_handle(request: GatewayForwardRequest) -> dict[str, Any]:
    """
    Handle forwarded events from the gateway.
    
    This endpoint receives events that clients send via WebSocket to the gateway,
    which then forwards them here for processing.
    """
    event = request.message.event
    session_id = request.message.data.get("session_id")
    
    log.log_event_received(
        event,
        device_id=request.client.device_id,
        session_id=session_id,
        data=request.message.data,
    )
    
    # Check sync handlers first
    sync_handler = SYNC_EVENT_HANDLERS.get(event)
    if sync_handler is not None:
        log.debug(f"Using sync handler for {event}", component="gateway", session_id=session_id)
        try:
            result = sync_handler(request.client, request.message.data)
            log.debug(f"Sync handler success for {event}", component="gateway", session_id=session_id)
            return result
        except HTTPException as e:
            log.error(
                f"HTTPException in sync handler: {e.status_code} - {e.detail}",
                component="gateway",
                session_id=session_id,
            )
            raise
        except Exception as e:
            log.error(f"Exception in sync handler for {event}: {e}", component="gateway", session_id=session_id, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    # Check async handlers
    async_handler = ASYNC_EVENT_HANDLERS.get(event)
    if async_handler is not None:
        log.debug(f"Using async handler for {event}", component="gateway", session_id=session_id)
        try:
            result = await async_handler(request.client, request.message.data)
            log.debug(f"Async handler success for {event}", component="gateway", session_id=session_id)
            return result
        except HTTPException as e:
            log.error(
                f"HTTPException in async handler: {e.status_code} - {e.detail}",
                component="gateway",
                session_id=session_id,
            )
            raise
        except Exception as e:
            log.error(f"Exception in async handler for {event}: {e}", component="gateway", session_id=session_id, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
    
    log.warning(f"Unknown event received: {event}", component="gateway", device_id=request.client.device_id)
    raise HTTPException(
        status_code=400,
        detail=f"Unknown event: {event}"
    )
