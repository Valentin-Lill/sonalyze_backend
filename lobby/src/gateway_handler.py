"""Gateway handler for receiving forwarded events from the gateway service."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from models import ParticipantRole
from service import (
    assign_role,
    create_lobby,
    get_lobby_by_code,
    get_lobby_by_id,
    join_lobby,
    leave_lobby,
    list_participants,
    share_room_snapshot,
    start_measurement,
)
from schemas import ParticipantOut
from measurement_coordinator import (
    cancel_session,
    client_ready,
    create_session,
    get_session_status,
    handle_error,
    playback_complete,
    recording_started,
    recording_uploaded,
    speaker_audio_ready,
    start_measurement as start_measurement_session,
)

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


async def _handle_lobby_create(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """Handle lobby.create event."""
    lobby = await create_lobby(session, creator_device_id=client.device_id)
    await session.commit()
    return {
        "lobby_id": lobby.id,
        "code": lobby.code,
        "admin_device_id": lobby.creator_device_id,
        "state": lobby.state.value,
    }


async def _handle_lobby_join(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """Handle lobby.join event."""
    code = data.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' in data")
    
    lobby = await get_lobby_by_code(session, code)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")
    
    await join_lobby(session, lobby=lobby, device_id=client.device_id)
    participants = await list_participants(session, lobby.id)
    await session.commit()
    
    return {
        "lobby_id": lobby.id,
        "code": lobby.code,
        "admin_device_id": lobby.creator_device_id,
        "state": lobby.state.value,
        "participants": [
            ParticipantOut(
                device_id=p.device_id,
                role=p.role,
                role_slot_id=p.role_slot_id,
                role_slot_label=p.role_slot_label,
                status=p.status,
                joined_at=p.joined_at,
                left_at=p.left_at,
            ).model_dump(mode="json")
            for p in participants
        ],
    }


async def _handle_lobby_leave(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """Handle lobby.leave event."""
    lobby_id = data.get("lobby_id")
    if not lobby_id:
        raise HTTPException(status_code=400, detail="Missing 'lobby_id' in data")
    
    lobby = await get_lobby_by_id(session, lobby_id)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")
    
    await leave_lobby(session, lobby=lobby, device_id=client.device_id)
    await session.commit()
    return {"ok": True}


async def _handle_lobby_get(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """Handle lobby.get event."""
    lobby_id = data.get("lobby_id")
    code = data.get("code")
    
    if lobby_id:
        lobby = await get_lobby_by_id(session, lobby_id)
    elif code:
        lobby = await get_lobby_by_code(session, code)
    else:
        raise HTTPException(status_code=400, detail="Missing 'lobby_id' or 'code' in data")
    
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")
    
    participants = await list_participants(session, lobby.id)
    return {
        "lobby_id": lobby.id,
        "code": lobby.code,
        "admin_device_id": lobby.creator_device_id,
        "state": lobby.state.value,
        "participants": [
            ParticipantOut(
                device_id=p.device_id,
                role=p.role,
                role_slot_id=p.role_slot_id,
                role_slot_label=p.role_slot_label,
                status=p.status,
                joined_at=p.joined_at,
                left_at=p.left_at,
            ).model_dump(mode="json")
            for p in participants
        ],
    }


async def _handle_role_assign(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """Handle role.assign event."""
    lobby_id = data.get("lobby_id")
    target_device_id = data.get("target_device_id")
    role_str = data.get("role")
    role_slot_id = data.get("role_slot_id")
    role_slot_label = data.get("role_slot_label")
    
    if not lobby_id or not target_device_id or not role_str:
        raise HTTPException(
            status_code=400,
            detail="Missing 'lobby_id', 'target_device_id', or 'role' in data"
        )
    
    lobby = await get_lobby_by_id(session, lobby_id)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")
    
    try:
        role = ParticipantRole(role_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {role_str}")
    
    try:
        await assign_role(
            session,
            lobby=lobby,
            admin_device_id=client.device_id,
            target_device_id=target_device_id,
            role=role,
            role_slot_id=role_slot_id,
            role_slot_label=role_slot_label,
        )
        await session.commit()
        return {"ok": True}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


async def _handle_lobby_start(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """Handle lobby.start event (start measurement)."""
    lobby_id = data.get("lobby_id")
    if not lobby_id:
        raise HTTPException(status_code=400, detail="Missing 'lobby_id' in data")
    
    lobby = await get_lobby_by_id(session, lobby_id)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")
    
    try:
        await start_measurement(session, lobby=lobby, admin_device_id=client.device_id)
        await session.commit()
        return {"ok": True, "state": lobby.state.value}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


async def _handle_lobby_room_snapshot(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    lobby_id = data.get("lobby_id")
    room = data.get("room")
    if not lobby_id:
        raise HTTPException(status_code=400, detail="Missing 'lobby_id' in data")
    if room is None:
        raise HTTPException(status_code=400, detail="Missing 'room' in data")

    lobby = await get_lobby_by_id(session, lobby_id)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")

    if not isinstance(room, dict):
        raise HTTPException(status_code=400, detail="'room' must be an object")

    try:
        await share_room_snapshot(
            session,
            lobby=lobby,
            admin_device_id=client.device_id,
            room=room,
        )
        await session.commit()
        return {"ok": True}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# =============================================================================
# Measurement Session Coordination Handlers
# =============================================================================

async def _handle_measurement_create_session(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
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
    
    logger.info(
        f"Creating measurement session job_id={job_id} lobby_id={lobby_id} "
        f"speakers={len(speakers)} microphones={len(microphones)}"
    )
    
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
    
    measurement_session = await create_session(
        job_id=job_id,
        lobby_id=lobby_id,
        speakers=speakers,
        microphones=microphones,
    )
    
    return {
        "session_id": measurement_session.session_id,
        "job_id": job_id,
        "lobby_id": lobby_id,
        "total_speakers": len(speakers),
        "total_microphones": len(microphones),
    }


async def _handle_measurement_start_speaker(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """
    Handle measurement.start_speaker event (Step 2).
    
    Starts the measurement cycle for the next speaker.
    This will notify all clients via "measurement.start_measurement".
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    logger.info(f"Starting speaker measurement for session {session_id}")
    
    try:
        return await start_measurement_session(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_client_ready(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """
    Handle measurement.ready event (Step 3).
    
    Called by speakers and microphones when they are ready.
    When all clients are ready, audio is requested from the speaker.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    try:
        return await client_ready(session_id, client.device_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_speaker_audio_ready(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
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
    
    try:
        return await speaker_audio_ready(session_id, client.device_id, audio_hash)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_recording_started(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """
    Handle measurement.recording_started event (Step 7).
    
    Called by microphones when they have started recording.
    When all microphones are recording, playback is triggered.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    try:
        return await recording_started(session_id, client.device_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_playback_complete(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """
    Handle measurement.playback_complete event (Step 9).
    
    Called by the speaker when audio playback is complete.
    This signals microphones to stop recording and upload.
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    try:
        return await playback_complete(session_id, client.device_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_speaker_finished(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """
    Handle measurement.speaker_finished event (LEGACY - redirects to playback_complete).
    """
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    logger.warning("measurement.speaker_finished is deprecated, use measurement.playback_complete")
    
    try:
        return await playback_complete(session_id, client.device_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_recording_uploaded(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
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
    
    try:
        return await recording_uploaded(session_id, client.device_id, upload_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_error(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
) -> dict[str, Any]:
    """
    Handle measurement.error event.
    
    Called by any client when an error occurs during measurement.
    """
    session_id = data.get("session_id")
    error_message = data.get("error_message", "Unknown error")
    error_code = data.get("error_code")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    try:
        return await handle_error(session_id, client.device_id, error_message, error_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _handle_measurement_session_status(
    client: GatewayClientInfo,
    data: dict[str, Any],
    session: AsyncSession,
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
    session: AsyncSession,
) -> dict[str, Any]:
    """
    Handle measurement.cancel_session event.
    
    Cancels an ongoing measurement session.
    """
    session_id = data.get("session_id")
    reason = data.get("reason", "cancelled_by_client")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing 'session_id' in data")
    
    try:
        return await cancel_session(session_id, reason)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# Event handlers mapping - all lobby and session management events
EVENT_HANDLERS = {
    # Lobby events
    "lobby.create": _handle_lobby_create,
    "lobby.join": _handle_lobby_join,
    "lobby.leave": _handle_lobby_leave,
    "lobby.get": _handle_lobby_get,
    "lobby.start": _handle_lobby_start,
    "role.assign": _handle_role_assign,
    "lobby.room_snapshot": _handle_lobby_room_snapshot,
    
    # Measurement session management events
    "measurement.create_session": _handle_measurement_create_session,
    "measurement.start_speaker": _handle_measurement_start_speaker,
    "measurement.session_status": _handle_measurement_session_status,
    "measurement.cancel_session": _handle_measurement_cancel_session,
    
    # Measurement protocol events (11-step)
    "measurement.ready": _handle_measurement_client_ready,
    "measurement.client_ready": _handle_measurement_client_ready,  # Alias
    "measurement.speaker_audio_ready": _handle_measurement_speaker_audio_ready,
    "measurement.recording_started": _handle_measurement_recording_started,
    "measurement.playback_complete": _handle_measurement_playback_complete,
    "measurement.speaker_finished": _handle_measurement_speaker_finished,  # Legacy
    "measurement.recording_uploaded": _handle_measurement_recording_uploaded,
    "measurement.error": _handle_measurement_error,
}


@router.post("/gateway/handle")
async def gateway_handle(
    request: GatewayForwardRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Handle forwarded events from the gateway.
    
    This endpoint receives events that clients send via WebSocket to the gateway,
    which then forwards them here for processing.
    """
    event = request.message.event
    handler = EVENT_HANDLERS.get(event)
    
    if handler is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event: {event}"
        )
    
    try:
        return await handler(request.client, request.message.data, session)
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
