"""
Measurement Coordinator Module for Lobby Service.

Implements the 11-step synchronized measurement protocol:

1. Lobby creator tells backend measurements should start
2. Server tells all clients that measurement will start now
3. All clients send a ready signal
4. Speaker requests the audiofile + hash
5. Backend sends speaker audiofile (.wav) with hash for verification
6. Speaker tells backend it received working audiofile, ready to start
7. Backend tells all microphones to start recording now
8. Microphones start recording and confirm to backend
9. Backend tells loudspeaker to start playing audiofile
10. Speaker plays, when finished tells backend
11. Backend tells microphones to stop, they send recordings to backend

This module maintains the state machine for measurement sessions.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from broadcast import broadcast_to_devices
from settings import settings

# Initialize logger
logger = logging.getLogger("measurement_coordinator")


class MeasurementPhase(str, enum.Enum):
    """Phases of a measurement cycle following the 11-step protocol."""
    IDLE = "idle"
    # Step 1: Creator initiated start
    INITIATING = "initiating"
    # Step 2: Server notifying clients
    NOTIFYING_CLIENTS = "notifying_clients"
    # Step 3: Waiting for ready signals
    WAITING_READY = "waiting_ready"
    # Step 4-5: Speaker requesting/receiving audio
    SPEAKER_DOWNLOADING = "speaker_downloading"
    # Step 6: Speaker confirmed audio ready
    SPEAKER_READY = "speaker_ready"
    # Step 7: Commanding microphones to start recording
    STARTING_RECORDING = "starting_recording"
    # Step 8: Microphones recording
    RECORDING = "recording"
    # Step 9: Speaker playing
    PLAYING = "playing"
    # Step 10: Playback complete, stopping recording
    PLAYBACK_COMPLETE = "playback_complete"
    # Step 11: Uploading recordings
    UPLOADING = "uploading"
    # Processing
    PROCESSING = "processing"
    # Complete
    COMPLETED = "completed"
    # Error
    FAILED = "failed"


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
    recording_started: bool = False
    audio_received: bool = False
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
    audio_hash: str | None = None
    error: str | None = None

    @property
    def all_ready(self) -> bool:
        """Check if speaker and all microphones are ready."""
        return self.speaker.is_ready and all(m.is_ready for m in self.microphones)

    @property
    def all_recordings_started(self) -> bool:
        """Check if all microphones have started recording."""
        return all(m.recording_started for m in self.microphones)

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


async def _broadcast_to_devices(
    device_ids: list[str],
    event: str,
    data: dict[str, Any],
    session_id: str | None = None,
) -> None:
    """Broadcast an event to specific devices via the gateway."""
    if not device_ids:
        logger.warning(
            f"broadcast_to_devices: No device IDs provided for event {event}",
        )
        return

    logger.debug(
        f"Broadcasting {event} to {len(device_ids)} devices (session={session_id})"
    )

    await broadcast_to_devices(device_ids, event, data)


async def _broadcast_phase_update(
    session: MeasurementSession,
    phase: MeasurementPhase,
    extra_data: dict[str, Any] | None = None,
) -> None:
    """
    Broadcast measurement phase update to ALL session participants.
    
    This ensures all clients (not just the admin) receive real-time updates
    about which step of the measurement timeline they are on.
    """
    all_device_ids = (
        [s.device_id for s in session.speakers] +
        [m.device_id for m in session.microphones]
    )
    
    data = {
        "session_id": session.session_id,
        "job_id": session.job_id,
        "phase": phase.value,
        "phase_description": _get_phase_description(phase),
        "current_speaker_index": session.current_speaker_index,
        "total_speakers": len(session.speakers),
        "completed_speakers": len(session.completed_measurements),
    }
    
    if extra_data:
        data.update(extra_data)
    
    await _broadcast_to_devices(
        all_device_ids,
        "measurement.phase_update",
        data,
        session_id=session.session_id,
    )


def _get_phase_description(phase: MeasurementPhase) -> str:
    """Get a human-readable description for a measurement phase."""
    descriptions = {
        MeasurementPhase.IDLE: "Idle - Waiting to start",
        MeasurementPhase.INITIATING: "Initiating measurement",
        MeasurementPhase.NOTIFYING_CLIENTS: "Notifying all devices",
        MeasurementPhase.WAITING_READY: "Waiting for devices to be ready",
        MeasurementPhase.SPEAKER_DOWNLOADING: "Speaker downloading audio",
        MeasurementPhase.SPEAKER_READY: "Speaker ready to play",
        MeasurementPhase.STARTING_RECORDING: "Starting recording on microphones",
        MeasurementPhase.RECORDING: "Recording in progress",
        MeasurementPhase.PLAYING: "Playing measurement signal",
        MeasurementPhase.PLAYBACK_COMPLETE: "Playback complete",
        MeasurementPhase.UPLOADING: "Uploading recordings",
        MeasurementPhase.PROCESSING: "Processing recordings",
        MeasurementPhase.COMPLETED: "Measurement complete",
        MeasurementPhase.FAILED: "Measurement failed",
    }
    return descriptions.get(phase, phase.value)


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
    
    logger.info(
        f"Creating measurement session session_id={session_id} job_id={job_id} "
        f"lobby_id={lobby_id} speakers={len(speakers)} microphones={len(microphones)}"
    )
    
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
    
    logger.info(f"Session {session_id} created successfully")
    
    return session


async def get_session(session_id: str) -> MeasurementSession | None:
    """Get a measurement session by ID."""
    async with _sessions_lock:
        return _sessions.get(session_id)


async def start_measurement(session_id: str) -> dict[str, Any]:
    """
    Step 2: Start measurement - Notify all clients.
    
    Backend sends "measurement.start_measurement" to all speakers and microphones
    with the session ID. Clients should prepare for measurement.
    
    Returns:
        Status dict with session state
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    if session.current_speaker_index >= len(session.speakers):
        session.status = "completed"
        logger.info(f"All speakers measured for session {session_id}")
        return {
            "session_id": session_id,
            "status": "completed",
            "completed_speakers": session.completed_measurements,
        }
    
    speaker = session.speakers[session.current_speaker_index]
    
    # Reset states for all clients
    for mic in session.microphones:
        mic.is_ready = False
        mic.is_finished = False
        mic.recording_uploaded = False
        mic.recording_started = False
        mic.error = None
    
    speaker.is_ready = False
    speaker.is_finished = False
    speaker.audio_received = False
    speaker.error = None
    
    # Create the measurement state
    measurement = SpeakerMeasurement(
        speaker=speaker,
        microphones=session.microphones.copy(),
        phase=MeasurementPhase.INITIATING,
        started_at=datetime.utcnow(),
    )
    session.current_measurement = measurement
    session.status = "running"
    
    logger.info(
        f"Starting measurement for session {session_id} speaker={speaker.slot_id}"
    )
    
    # Step 2: Notify ALL clients (speakers + microphones) that measurement is starting
    all_device_ids = [s.device_id for s in session.speakers] + [m.device_id for m in session.microphones]
    await _broadcast_to_devices(
        all_device_ids,
        "measurement.start_measurement",
        {
            "session_id": session_id,
            "job_id": session.job_id,
            "current_speaker_slot_id": speaker.slot_id,
            "current_speaker_slot_label": speaker.slot_label,
            "speaker_device_id": speaker.device_id,
            "total_microphones": len(session.microphones),
        },
        session_id=session_id,
    )
    
    measurement.phase = MeasurementPhase.NOTIFYING_CLIENTS
    
    # Broadcast phase update to all clients
    await _broadcast_phase_update(session, measurement.phase)
    
    return {
        "session_id": session_id,
        "status": "notifying_clients",
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
    Step 3: Handle client ready acknowledgment.
    
    Each client sends "measurement.ready" when they are prepared.
    When all clients are ready, we request audio from the speaker.
    
    Returns:
        Status dict
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    measurement = session.current_measurement
    if measurement is None:
        raise ValueError("No active measurement")
    
    logger.debug(f"Client ready: device={device_id} session={session_id}")
    
    # Mark the client as ready
    if measurement.speaker.device_id == device_id:
        measurement.speaker.is_ready = True
        logger.debug(f"Speaker {device_id} marked ready")
    else:
        for mic in measurement.microphones:
            if mic.device_id == device_id:
                mic.is_ready = True
                logger.debug(f"Microphone {device_id} marked ready")
                break
    
    # Count ready status
    ready_mics = sum(1 for m in measurement.microphones if m.is_ready)
    total_mics = len(measurement.microphones)
    
    logger.info(
        f"Ready status: speaker={measurement.speaker.is_ready}, mics={ready_mics}/{total_mics}"
    )
    
    # Check if all clients are ready
    if measurement.all_ready:
        logger.info(f"All clients ready for session {session_id}, requesting audio")
        
        # Step 4: Request audio from speaker
        # Use gateway_url for external clients to download audio through the gateway proxy
        measurement.phase = MeasurementPhase.SPEAKER_DOWNLOADING
        
        # Broadcast phase update to all clients
        await _broadcast_phase_update(session, measurement.phase)
        
        await _broadcast_to_devices(
            [measurement.speaker.device_id],
            "measurement.request_audio",
            {
                "session_id": session_id,
                "audio_url": f"{settings.gateway_url}/v1/measurement/audio?session_id={session_id}",
            },
            session_id=session_id,
        )
        
        return {
            "session_id": session_id,
            "status": "all_ready",
            "action": "requesting_audio_from_speaker",
        }
    
    return {
        "session_id": session_id,
        "status": "waiting",
        "speaker_ready": measurement.speaker.is_ready,
        "microphones_ready": f"{ready_mics}/{total_mics}",
    }


async def speaker_audio_ready(
    session_id: str,
    device_id: str,
    audio_hash: str | None = None,
) -> dict[str, Any]:
    """
    Step 5: Handle speaker confirming audio is downloaded and ready.
    
    When speaker sends "measurement.speaker_audio_ready", we command all
    microphones to start recording.
    
    Returns:
        Status dict
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    measurement = session.current_measurement
    if measurement is None:
        raise ValueError("No active measurement")
    
    logger.info(f"Speaker audio ready: device={device_id} session={session_id} hash={audio_hash}")
    
    if measurement.speaker.device_id != device_id:
        raise ValueError("Only the current speaker can signal audio ready")
    
    measurement.speaker.audio_received = True
    measurement.audio_hash = audio_hash
    measurement.phase = MeasurementPhase.SPEAKER_READY
    
    # Broadcast phase update to all clients
    await _broadcast_phase_update(session, measurement.phase)
    
    # Step 6: Command all microphones to start recording
    measurement.phase = MeasurementPhase.STARTING_RECORDING
    
    # Broadcast phase update to all clients
    await _broadcast_phase_update(session, measurement.phase)
    
    mic_device_ids = [m.device_id for m in measurement.microphones]
    
    await _broadcast_to_devices(
        mic_device_ids,
        "measurement.start_recording",
        {
            "session_id": session_id,
            "speaker_slot_id": measurement.speaker.slot_id,
            "expected_duration_seconds": 15.0,
        },
        session_id=session_id,
    )
    
    return {
        "session_id": session_id,
        "status": "commanding_recording_start",
        "audio_hash": audio_hash,
    }


async def recording_started(
    session_id: str,
    device_id: str,
) -> dict[str, Any]:
    """
    Step 7: Handle microphone confirming recording has started.
    
    When ALL microphones confirm recording started, we command the speaker
    to start playback.
    
    Returns:
        Status dict
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    measurement = session.current_measurement
    if measurement is None:
        raise ValueError("No active measurement")
    
    logger.debug(f"Recording started: device={device_id} session={session_id}")
    
    # Mark the microphone as recording
    for mic in measurement.microphones:
        if mic.device_id == device_id:
            mic.recording_started = True
            logger.debug(f"Microphone {device_id} started recording")
            break
    
    # Count recordings started
    started_count = sum(1 for m in measurement.microphones if m.recording_started)
    total_count = len(measurement.microphones)
    
    logger.info(f"Recordings started: {started_count}/{total_count}")
    
    # Check if all microphones are recording
    if measurement.all_recordings_started:
        logger.info(f"All recordings started, commanding playback for session {session_id}")
        
        # Step 8: Command speaker to start playback
        measurement.phase = MeasurementPhase.PLAYING
        
        # Broadcast phase update to all clients
        await _broadcast_phase_update(session, measurement.phase)
        
        await _broadcast_to_devices(
            [measurement.speaker.device_id],
            "measurement.start_playback",
            {
                "session_id": session_id,
            },
            session_id=session_id,
        )
        
        return {
            "session_id": session_id,
            "status": "all_recording",
            "action": "playback_commanded",
        }
    
    # Broadcast updated recording count to all clients
    await _broadcast_phase_update(
        session,
        measurement.phase,
        extra_data={
            "recordings_started": started_count,
            "total_microphones": total_count,
        },
    )
    
    return {
        "session_id": session_id,
        "status": "waiting_recordings",
        "recordings_started": f"{started_count}/{total_count}",
    }


async def playback_complete(
    session_id: str,
    device_id: str,
) -> dict[str, Any]:
    """
    Step 9: Handle speaker signaling playback is complete.
    
    When speaker sends "measurement.playback_complete", we command all
    microphones to stop recording and upload.
    
    Returns:
        Status dict
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    measurement = session.current_measurement
    if measurement is None:
        raise ValueError("No active measurement")
    
    logger.info(f"Playback complete: device={device_id} session={session_id}")
    
    if measurement.speaker.device_id != device_id:
        raise ValueError("Only the current speaker can signal playback complete")
    
    measurement.speaker.is_finished = True
    measurement.phase = MeasurementPhase.PLAYBACK_COMPLETE
    
    # Broadcast phase update to all clients
    await _broadcast_phase_update(session, measurement.phase)
    
    # Step 10: Command all microphones to stop recording and upload
    # Use gateway_url for external clients to upload recordings through the gateway proxy
    measurement.phase = MeasurementPhase.UPLOADING
    
    # Broadcast phase update to all clients
    await _broadcast_phase_update(session, measurement.phase)
    
    mic_device_ids = [m.device_id for m in measurement.microphones]
    
    await _broadcast_to_devices(
        mic_device_ids,
        "measurement.stop_recording",
        {
            "session_id": session_id,
            "job_id": session.job_id,
            "speaker_slot_id": measurement.speaker.slot_id,
            "upload_endpoint": f"{settings.gateway_url}/v1/jobs/{session.job_id}/uploads/",
        },
        session_id=session_id,
    )
    
    return {
        "session_id": session_id,
        "status": "playback_complete",
        "action": "commanding_upload",
    }


async def recording_uploaded(
    session_id: str,
    device_id: str,
    upload_name: str,
) -> dict[str, Any]:
    """
    Step 11: Handle microphone signaling their recording was uploaded.
    
    When all recordings are uploaded, trigger processing or move to next speaker.
    
    Returns:
        Status dict
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    measurement = session.current_measurement
    if measurement is None:
        raise ValueError("No active measurement")
    
    logger.info(f"Recording uploaded: device={device_id} session={session_id} upload={upload_name}")
    
    # Mark the microphone as having uploaded
    for mic in measurement.microphones:
        if mic.device_id == device_id:
            mic.recording_uploaded = True
            logger.debug(f"Microphone {device_id} uploaded recording")
            break
    
    # Count uploads
    uploaded_count = sum(1 for m in measurement.microphones if m.recording_uploaded)
    total_count = len(measurement.microphones)
    
    logger.info(f"Recordings uploaded: {uploaded_count}/{total_count}")
    
    # Check if all recordings are uploaded
    if measurement.all_recordings_uploaded:
        logger.info(f"All recordings uploaded for session {session_id}")
        
        measurement.phase = MeasurementPhase.PROCESSING
        measurement.finished_at = datetime.utcnow()
        
        # Broadcast phase update to all clients
        await _broadcast_phase_update(session, measurement.phase)
        
        # Add to completed measurements
        session.completed_measurements.append(measurement.speaker.slot_id)
        session.current_speaker_index += 1
        
        # Notify all participants of progress
        all_device_ids = [s.device_id for s in session.speakers] + [m.device_id for m in session.microphones]
        
        # Check if there are more speakers
        if session.current_speaker_index < len(session.speakers):
            await _broadcast_to_devices(
                all_device_ids,
                "measurement.speaker_complete",
                {
                    "session_id": session_id,
                    "completed_speaker_slot_id": measurement.speaker.slot_id,
                    "remaining_speakers": len(session.speakers) - session.current_speaker_index,
                },
                session_id=session_id,
            )
            
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
            
            logger.info(f"Measurement session {session_id} complete")
            
            # Broadcast phase update to all clients
            await _broadcast_phase_update(session, measurement.phase)
            
            await _broadcast_to_devices(
                all_device_ids,
                "measurement.session_complete",
                {
                    "session_id": session_id,
                    "job_id": session.job_id,
                    "completed_speakers": session.completed_measurements,
                    "audio_hash": measurement.audio_hash,
                },
                session_id=session_id,
            )
            
            return {
                "session_id": session_id,
                "status": "session_complete",
                "completed_speakers": session.completed_measurements,
                "audio_hash": measurement.audio_hash,
            }
    
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
            "speaker_audio_received": m.speaker.audio_received,
            "microphones_ready": sum(1 for mic in m.microphones if mic.is_ready),
            "recordings_started": sum(1 for mic in m.microphones if mic.recording_started),
            "recordings_uploaded": sum(1 for mic in m.microphones if mic.recording_uploaded),
            "audio_hash": m.audio_hash,
        }
    
    return result


async def cancel_session(session_id: str, reason: str = "cancelled_by_admin") -> dict[str, Any]:
    """Cancel a measurement session and notify all clients."""
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    logger.warning(f"Cancelling session {session_id}: {reason}")
    
    session.status = "cancelled"
    if session.current_measurement:
        session.current_measurement.phase = MeasurementPhase.FAILED
        session.current_measurement.error = reason
    
    # Notify all participants
    all_device_ids = (
        [s.device_id for s in session.speakers] +
        [m.device_id for m in session.microphones]
    )
    await _broadcast_to_devices(
        all_device_ids,
        "measurement.session_cancelled",
        {"session_id": session_id, "reason": reason},
        session_id=session_id,
    )
    
    return {"session_id": session_id, "status": "cancelled", "reason": reason}


async def handle_error(
    session_id: str,
    device_id: str,
    error_message: str,
    error_code: str | None = None,
) -> dict[str, Any]:
    """
    Handle an error reported by a client during measurement.
    
    This may cancel the current measurement depending on severity.
    
    Returns:
        Status dict
    """
    session = await get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    
    logger.error(
        f"Client error: session={session_id} device={device_id} error={error_message} code={error_code}"
    )
    
    measurement = session.current_measurement
    if measurement:
        measurement.error = error_message
        measurement.phase = MeasurementPhase.FAILED
    
    # Notify all participants of the error
    all_device_ids = (
        [s.device_id for s in session.speakers] +
        [m.device_id for m in session.microphones]
    )
    await _broadcast_to_devices(
        all_device_ids,
        "measurement.error",
        {
            "session_id": session_id,
            "error_device_id": device_id,
            "error_message": error_message,
            "error_code": error_code,
        },
        session_id=session_id,
    )
    
    return {
        "session_id": session_id,
        "status": "error",
        "error_device_id": device_id,
        "error_message": error_message,
    }


async def broadcast_analysis_results(
    session_id: str,
    job_id: str,
    results: dict[str, Any],
) -> dict[str, Any]:
    """
    Broadcast analysis results to all session participants.
    
    This is called after the measurement service completes analysis.
    It ensures all clients (not just the admin) receive the results.
    
    Args:
        session_id: The measurement session ID
        job_id: The job ID containing the analysis
        results: The analysis results dict
    
    Returns:
        Status dict
    """
    session = await get_session(session_id)
    if session is None:
        # Session might have been cleaned up, try to broadcast to stored device IDs
        logger.warning(f"Session not found for results broadcast: {session_id}")
        raise ValueError(f"Session not found: {session_id}")
    
    logger.info(f"Broadcasting analysis results for session {session_id}")
    
    # Notify all participants of the analysis results
    all_device_ids = (
        [s.device_id for s in session.speakers] +
        [m.device_id for m in session.microphones]
    )
    
    await _broadcast_to_devices(
        all_device_ids,
        "measurement.analysis_results",
        {
            "session_id": session_id,
            "job_id": job_id,
            "results": results,
        },
        session_id=session_id,
    )
    
    logger.info(f"Analysis results broadcast to {len(all_device_ids)} devices")
    
    return {
        "session_id": session_id,
        "status": "results_broadcast",
        "devices_notified": len(all_device_ids),
    }


async def get_session_device_ids(session_id: str) -> list[str]:
    """
    Get all device IDs for a session (for external broadcast).
    
    Args:
        session_id: The measurement session ID
        
    Returns:
        List of device IDs in the session
    """
    session = await get_session(session_id)
    if session is None:
        return []
    
    return (
        [s.device_id for s in session.speakers] +
        [m.device_id for m in session.microphones]
    )
