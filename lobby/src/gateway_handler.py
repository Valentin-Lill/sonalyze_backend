"""Gateway handler for receiving forwarded events from the gateway service."""
from __future__ import annotations

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


# Event handlers mapping
EVENT_HANDLERS = {
    "lobby.create": _handle_lobby_create,
    "lobby.join": _handle_lobby_join,
    "lobby.leave": _handle_lobby_leave,
    "lobby.get": _handle_lobby_get,
    "lobby.start": _handle_lobby_start,
    "role.assign": _handle_role_assign,
    "lobby.room_snapshot": _handle_lobby_room_snapshot,
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
