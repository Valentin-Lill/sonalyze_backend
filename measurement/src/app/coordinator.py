"""
Measurement Coordinator Module.

Coordinates the synchronized measurement process between speakers and microphones:
1. Prepare all clients (speaker + microphones) for measurement
2. Wait for all clients to signal ready
3. Signal speaker to start playback
4. Wait for speaker to finish
5. Signal microphones to stop recording and upload
6. Collect and process recordings
7. Repeat for each speaker

This module maintains the state machine for measurement sessions.
"""
from __future__ import annotations

import asyncio
import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable

import httpx

from app.settings import settings


class MeasurementPhase(str, enum.Enum):
    """Phases of a measurement cycle for a single speaker."""
    IDLE = "idle"
    PREPARING = "preparing"  # Notifying clients to prepare
    WAITING_READY = "waiting_ready"  # Waiting for all clients to be ready
    PLAYING = "playing"  # Speaker is playing the measurement signal
    RECORDING_COMPLETE = "recording_complete"  # Waiting for recordings to be uploaded
    PROCESSING = "processing"  # Processing the recordings
    COMPLETED = "completed"  # Measurement cycle complete
    FAILED = "failed"  # Measurement failed


class ClientRole(str, enum.Enum):
    """Role of a client in the measurement."""
    SPEAKER = "speaker"
    MICROPHONE = "microphone"


@dataclass
class MeasurementClient:
    """Represents a client participating in a measurement."""
    device_id: str
    role: ClientRole
    slot_id: str
    slot_label: str | None = None
    is_ready: bool = False
    is_finished: bool = False
    recording_uploaded: bool = False
    error: str | None = None


@dataclass
class SpeakerMeasurement:
    """State for measuring a single speaker with all microphones."""
    speaker: MeasurementClient
    microphones: list[MeasurementClient]
    phase: MeasurementPhase = MeasurementPhase.IDLE
    started_at: datetime | None = None
    finished_at: datetime | None = None
    audio_file_id: str | None = None
    error: str | None = None
    
    @property
    def all_ready(self) -> bool:
        """Check if speaker and all microphones are ready."""
        return self.speaker.is_ready and all(m.is_ready for m in self.microphones)
    
    @property
    def all_recordings_uploaded(self) -> bool:
        """Check if all microphones have uploaded their recordings."""
        return all(m.recording_uploaded for m in self.microphones)


@dataclass
class MeasurementSession:
    """
    Complete measurement session state.
    
    A session involves measuring each speaker with all microphones.
    """
    session_id: str
    job_id: str
    lobby_id: str
    speakers: list[MeasurementClient]
    microphones: list[MeasurementClient]
    current_speaker_index: int = 0
    current_measurement: SpeakerMeasurement | None = None
    completed_measurements: list[str] = field(default_factory=list)  # speaker slot IDs
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "created"  # created, running, completed, failed
    error: str | None = None


# In-memory session store (for simplicity; consider Redis for production)
_sessions: dict[str, MeasurementSession] = {}
_sessions_lock = asyncio.Lock()


async def broadcast_to_devices(
    device_ids: list[str],
    event: str,
    data: dict[str, Any],
) -> None:
    """Broadcast an event to specific devices via the gateway."""
    if not device_ids:
        print(f"[coordinator] broadcast_to_devices: No device IDs provided for event {event}")
        return
    
    url = f"{settings.gateway_url}/internal/broadcast"
    headers = {"X-Internal-Token": settings.internal_auth_token}
    payload = {
        "event": event,
        "data": data,
        "targets": {"device_ids": device_ids},
    }
    
    print(f"[coordinator] Broadcasting event '{event}' to devices: {device_ids}")
    print(f"[coordinator] Broadcast URL: {url}")
    print(f"[coordinator] Broadcast payload: {payload}")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=5.0)
            print(f"[coordinator] Broadcast response: status={response.status_code}, body={response.text}")
        except Exception as e:
            print(f"[coordinator] Failed to broadcast {event}: {e}")


async def create_session(
    job_id: str,
    lobby_id: str,
    speakers: list[dict[str, Any]],
    microphones: list[dict[str, Any]],
) -> MeasurementSession:
    """
    Create a new measurement session.
    
    Args:
        job_id: Associated job ID for storing results
        lobby_id: Lobby ID for participant management
        speakers: List of speaker info dicts with device_id, slot_id, slot_label
        microphones: List of microphone info dicts with device_id, slot_id, slot_label
    
    Returns:
        Created MeasurementSession
    """
    session_id = str(uuid.uuid4())
    
    speaker_clients = [
        MeasurementClient(
            device_id=s["device_id"],
            role=ClientRole.SPEAKER,
            slot_id=s["slot_id"],
            slot_label=s.get("slot_label"),
        )
        for s in speakers
    ]
    
    microphone_clients = [
        MeasurementClient(
            device_id=m["device_id"],
            role=ClientRole.MICROPHONE,
            slot_id=m["slot_id"],
            slot_label=m.get("slot_label"),
        )
        for m in microphones
    ]
    
    session = MeasurementSession(
        session_id=session_id,
        job_id=job_id,
        lobby_id=lobby_id,
        speakers=speaker_clients,
        microphones=microphone_clients,
    )
    
    async with _sessions_lock:
        _sessions[session_id] = session
    
    return session


async def get_session(session_id: str) -> MeasurementSession | None:
    """Get a measurement session by ID."""
    async with _sessions_lock:
        return _sessions.get(session_id)


async def start_next_speaker_measurement(session_id: str) -> dict[str, Any]:
    """
    Start measurement for the next speaker in the session.
    
    This initiates the prepare phase, notifying all clients to get ready.
    
    Returns:
        Status dict with session state
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    if session.current_speaker_index >= len(session.speakers):
        # All speakers measured
        session.status = "completed"
        return {
            "session_id": session_id,
            "status": "completed",
            "completed_speakers": session.completed_measurements,
        }
    
    speaker = session.speakers[session.current_speaker_index]
    
    # Reset ready states for microphones
    for mic in session.microphones:
        mic.is_ready = False
        mic.is_finished = False
        mic.recording_uploaded = False
        mic.error = None
    
    speaker.is_ready = False
    speaker.is_finished = False
    speaker.error = None
    
    # Create the measurement state
    measurement = SpeakerMeasurement(
        speaker=speaker,
        microphones=session.microphones.copy(),
        phase=MeasurementPhase.PREPARING,
        started_at=datetime.utcnow(),
    )
    session.current_measurement = measurement
    session.status = "running"
    
    # Generate audio file ID for this measurement
    measurement.audio_file_id = f"measurement_{session_id}_{speaker.slot_id}"
    
    # Notify all microphones to prepare for recording
    mic_device_ids = [m.device_id for m in session.microphones]
    await broadcast_to_devices(
        mic_device_ids,
        "measurement.prepare_recording",
        {
            "session_id": session_id,
            "job_id": session.job_id,
            "speaker_slot_id": speaker.slot_id,
            "speaker_slot_label": speaker.slot_label,
            "expected_duration_seconds": 15.0,  # Total measurement duration
        },
    )
    
    # Notify the speaker to prepare for playback
    await broadcast_to_devices(
        [speaker.device_id],
        "measurement.prepare_playback",
        {
            "session_id": session_id,
            "job_id": session.job_id,
            "audio_file_endpoint": f"/v1/measurement/audio?session_id={session_id}",
            "speaker_slot_id": speaker.slot_id,
        },
    )
    
    measurement.phase = MeasurementPhase.WAITING_READY
    
    return {
        "session_id": session_id,
        "status": "preparing",
        "current_speaker": {
            "device_id": speaker.device_id,
            "slot_id": speaker.slot_id,
            "slot_label": speaker.slot_label,
        },
        "microphones": [
            {"device_id": m.device_id, "slot_id": m.slot_id}
            for m in session.microphones
        ],
    }


async def client_ready(
    session_id: str,
    device_id: str,
) -> dict[str, Any]:
    """
    Handle a client signaling they are ready.
    
    When all clients are ready, the speaker is signaled to start playback.
    
    Returns:
        Status dict
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    measurement = session.current_measurement
    if measurement is None:
        raise ValueError("No active measurement")
    
    if measurement.phase != MeasurementPhase.WAITING_READY:
        raise ValueError(f"Invalid phase for ready: {measurement.phase}")
    
    # Mark the client as ready
    if measurement.speaker.device_id == device_id:
        measurement.speaker.is_ready = True
    else:
        for mic in measurement.microphones:
            if mic.device_id == device_id:
                mic.is_ready = True
                break
    
    # Check if all clients are ready
    if measurement.all_ready:
        # Signal speaker to start playback
        measurement.phase = MeasurementPhase.PLAYING
        
        # Notify both speaker AND microphones that playback is starting
        # Microphones need this signal to start recording
        all_device_ids = [measurement.speaker.device_id] + [m.device_id for m in measurement.microphones]
        await broadcast_to_devices(
            all_device_ids,
            "measurement.start_playback",
            {
                "session_id": session_id,
                "speaker_slot_id": measurement.speaker.slot_id,
            },
        )
        
        return {
            "session_id": session_id,
            "status": "all_ready",
            "action": "playback_started",
        }
    
    # Count ready status
    ready_mics = sum(1 for m in measurement.microphones if m.is_ready)
    total_mics = len(measurement.microphones)
    
    return {
        "session_id": session_id,
        "status": "waiting",
        "speaker_ready": measurement.speaker.is_ready,
        "microphones_ready": f"{ready_mics}/{total_mics}",
    }


async def speaker_finished(session_id: str, device_id: str) -> dict[str, Any]:
    """
    Handle speaker signaling playback is complete.
    
    This triggers microphones to stop recording and upload.
    
    Returns:
        Status dict
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    measurement = session.current_measurement
    if measurement is None:
        raise ValueError("No active measurement")
    
    if measurement.speaker.device_id != device_id:
        raise ValueError("Only the current speaker can signal finished")
    
    if measurement.phase != MeasurementPhase.PLAYING:
        raise ValueError(f"Invalid phase for speaker_finished: {measurement.phase}")
    
    measurement.speaker.is_finished = True
    measurement.phase = MeasurementPhase.RECORDING_COMPLETE
    
    # Signal all microphones to stop and upload
    mic_device_ids = [m.device_id for m in measurement.microphones]
    await broadcast_to_devices(
        mic_device_ids,
        "measurement.stop_recording",
        {
            "session_id": session_id,
            "job_id": session.job_id,
            "speaker_slot_id": measurement.speaker.slot_id,
            "upload_endpoint": f"/v1/jobs/{session.job_id}/uploads/",
        },
    )
    
    return {
        "session_id": session_id,
        "status": "recording_complete",
        "waiting_for_uploads": True,
    }


async def recording_uploaded(
    session_id: str,
    device_id: str,
    upload_name: str,
) -> dict[str, Any]:
    """
    Handle a microphone signaling their recording was uploaded.
    
    When all recordings are uploaded, trigger analysis.
    
    Returns:
        Status dict
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    measurement = session.current_measurement
    if measurement is None:
        raise ValueError("No active measurement")
    
    # Mark the microphone as having uploaded
    for mic in measurement.microphones:
        if mic.device_id == device_id:
            mic.recording_uploaded = True
            break
    
    # Check if all recordings are uploaded
    if measurement.all_recordings_uploaded:
        measurement.phase = MeasurementPhase.PROCESSING
        measurement.finished_at = datetime.utcnow()
        
        # Add to completed measurements
        session.completed_measurements.append(measurement.speaker.slot_id)
        session.current_speaker_index += 1
        
        # Check if there are more speakers
        if session.current_speaker_index < len(session.speakers):
            # More speakers to measure
            return {
                "session_id": session_id,
                "status": "speaker_measurement_complete",
                "completed_speaker": measurement.speaker.slot_id,
                "next_speaker_available": True,
                "remaining_speakers": len(session.speakers) - session.current_speaker_index,
            }
        else:
            # All done
            session.status = "completed"
            measurement.phase = MeasurementPhase.COMPLETED
            
            # Notify all participants that measurement session is complete
            all_device_ids = [s.device_id for s in session.speakers] + [m.device_id for m in session.microphones]
            await broadcast_to_devices(
                all_device_ids,
                "measurement.session_complete",
                {
                    "session_id": session_id,
                    "job_id": session.job_id,
                    "completed_speakers": session.completed_measurements,
                },
            )
            
            return {
                "session_id": session_id,
                "status": "session_complete",
                "completed_speakers": session.completed_measurements,
            }
    
    # Still waiting for uploads
    uploaded_count = sum(1 for m in measurement.microphones if m.recording_uploaded)
    total_count = len(measurement.microphones)
    
    return {
        "session_id": session_id,
        "status": "waiting_uploads",
        "uploads_received": f"{uploaded_count}/{total_count}",
    }


async def get_session_status(session_id: str) -> dict[str, Any]:
    """Get the current status of a measurement session."""
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    result = {
        "session_id": session_id,
        "job_id": session.job_id,
        "lobby_id": session.lobby_id,
        "status": session.status,
        "total_speakers": len(session.speakers),
        "completed_speakers": len(session.completed_measurements),
        "speakers": [
            {
                "device_id": s.device_id,
                "slot_id": s.slot_id,
                "slot_label": s.slot_label,
                "completed": s.slot_id in session.completed_measurements,
            }
            for s in session.speakers
        ],
        "microphones": [
            {"device_id": m.device_id, "slot_id": m.slot_id, "slot_label": m.slot_label}
            for m in session.microphones
        ],
    }
    
    if session.current_measurement:
        m = session.current_measurement
        result["current_measurement"] = {
            "speaker_slot_id": m.speaker.slot_id,
            "phase": m.phase.value,
            "speaker_ready": m.speaker.is_ready,
            "microphones_ready": sum(1 for mic in m.microphones if mic.is_ready),
            "recordings_uploaded": sum(1 for mic in m.microphones if mic.recording_uploaded),
        }
    
    return result


async def cancel_session(session_id: str) -> dict[str, Any]:
    """Cancel a measurement session and notify all clients."""
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    session.status = "cancelled"
    if session.current_measurement:
        session.current_measurement.phase = MeasurementPhase.FAILED
    
    # Notify all participants
    all_device_ids = (
        [s.device_id for s in session.speakers] +
        [m.device_id for m in session.microphones]
    )
    await broadcast_to_devices(
        all_device_ids,
        "measurement.session_cancelled",
        {"session_id": session_id, "reason": "cancelled_by_admin"},
    )
    
    return {"session_id": session_id, "status": "cancelled"}
