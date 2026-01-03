from __future__ import annotations

import secrets
import string
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from broadcast import broadcast_to_devices
from models import Lobby, LobbyEvent, LobbyState, Participant, ParticipantRole, ParticipantStatus


def _generate_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _append_event(session: AsyncSession, lobby_id: str, event_type: str, payload: dict) -> LobbyEvent:
    event = LobbyEvent(lobby_id=lobby_id, type=event_type, payload=payload)
    session.add(event)
    await session.flush()
    return event


async def create_lobby(session: AsyncSession, creator_device_id: str) -> Lobby:
    # Best-effort unique code generation.
    for _ in range(10):
        code = _generate_code()
        existing = await session.scalar(select(Lobby).where(Lobby.code == code))
        if existing is None:
            lobby = Lobby(code=code, creator_device_id=creator_device_id, state=LobbyState.OPEN)
            session.add(lobby)
            await session.flush()

            session.add(
                Participant(
                    lobby_id=lobby.id,
                    device_id=creator_device_id,
                    role=ParticipantRole.NONE,
                    status=ParticipantStatus.JOINED,
                    joined_at=datetime.utcnow(),
                )
            )
            await _append_event(
                session,
                lobby.id,
                "lobby_created",
                {"admin_device_id": creator_device_id, "code": code},
            )
            return lobby

    raise RuntimeError("Could not generate a unique lobby code")


async def get_lobby_by_id(session: AsyncSession, lobby_id: str) -> Lobby | None:
    return await session.scalar(select(Lobby).where(Lobby.id == lobby_id))


async def get_lobby_by_code(session: AsyncSession, code: str) -> Lobby | None:
    return await session.scalar(select(Lobby).where(Lobby.code == code))


async def list_participants(session: AsyncSession, lobby_id: str) -> list[Participant]:
    result = await session.execute(select(Participant).where(Participant.lobby_id == lobby_id).order_by(Participant.joined_at.asc()))
    return list(result.scalars().all())


async def _broadcast_lobby_update(session: AsyncSession, lobby_id: str, event: str, data: dict) -> None:
    participants = await list_participants(session, lobby_id)
    # Filter only currently joined participants
    device_ids = [p.device_id for p in participants if p.status == ParticipantStatus.JOINED]
    if device_ids:
        await broadcast_to_devices(device_ids, event, data)


async def _broadcast_room_snapshot(
    session: AsyncSession,
    lobby_id: str,
    data: dict,
    *,
    exclude_device_id: str | None = None,
) -> None:
    participants = await list_participants(session, lobby_id)
    device_ids = [
        p.device_id
        for p in participants
        if p.status == ParticipantStatus.JOINED and p.device_id != exclude_device_id
    ]
    if device_ids:
        await broadcast_to_devices(device_ids, "lobby.room_snapshot", data)


async def join_lobby(session: AsyncSession, *, lobby: Lobby, device_id: str) -> Participant:
    if lobby.state != LobbyState.OPEN:
        raise ValueError("Lobby is not open")

    participant = await session.scalar(
        select(Participant).where(Participant.lobby_id == lobby.id, Participant.device_id == device_id)
    )

    if participant is None:
        participant = Participant(
            lobby_id=lobby.id,
            device_id=device_id,
            role=ParticipantRole.NONE,
            status=ParticipantStatus.JOINED,
            joined_at=datetime.utcnow(),
            left_at=None,
        )
        session.add(participant)
    else:
        participant.status = ParticipantStatus.JOINED
        participant.left_at = None

    await _append_event(session, lobby.id, "participant_joined", {"device_id": device_id})
    
    # Broadcast update to all participants
    await _broadcast_lobby_update(
        session, 
        lobby.id, 
        "lobby.updated", 
        {
            "type": "participant_joined",
            "device_id": device_id,
            "lobby_id": lobby.id
        }
    )
    
    return participant


async def leave_lobby(session: AsyncSession, *, lobby: Lobby, device_id: str) -> None:
    participant = await session.scalar(
        select(Participant).where(Participant.lobby_id == lobby.id, Participant.device_id == device_id)
    )
    if participant is None:
        return

    participant.status = ParticipantStatus.LEFT
    participant.left_at = datetime.utcnow()
    await _append_event(session, lobby.id, "participant_left", {"device_id": device_id})

    # Broadcast update to all participants
    await _broadcast_lobby_update(
        session, 
        lobby.id, 
        "lobby.updated", 
        {
            "type": "participant_left",
            "device_id": device_id,
            "lobby_id": lobby.id
        }
    )


def _require_admin(lobby: Lobby, admin_device_id: str) -> None:
    if lobby.creator_device_id != admin_device_id:
        raise PermissionError("Only the lobby admin can perform this action")


async def assign_role(
    session: AsyncSession,
    *,
    lobby: Lobby,
    admin_device_id: str,
    target_device_id: str,
    role: ParticipantRole,
    role_slot_id: str | None = None,
    role_slot_label: str | None = None,
) -> None:
    _require_admin(lobby, admin_device_id)

    participant = await session.scalar(
        select(Participant).where(Participant.lobby_id == lobby.id, Participant.device_id == target_device_id)
    )
    if participant is None or participant.status != ParticipantStatus.JOINED:
        raise LookupError("Target participant not found (or not joined)")

    participant.role = role
    if role == ParticipantRole.NONE:
        participant.role_slot_id = None
        participant.role_slot_label = None
    else:
        participant.role_slot_id = role_slot_id
        participant.role_slot_label = role_slot_label
    await _append_event(
        session,
        lobby.id,
        "role_assigned",
        {
            "admin_device_id": admin_device_id,
            "target_device_id": target_device_id,
            "role": role.value,
            "role_slot_id": participant.role_slot_id,
            "role_slot_label": participant.role_slot_label,
        },
    )

    # Broadcast update to all participants
    await _broadcast_lobby_update(
        session,
        lobby.id,
        "lobby.updated",
        {
            "type": "role_assigned",
            "target_device_id": target_device_id,
            "role": role.value,
            "lobby_id": lobby.id,
            "role_slot_id": participant.role_slot_id,
            "role_slot_label": participant.role_slot_label,
        },
    )


async def start_measurement(session: AsyncSession, *, lobby: Lobby, admin_device_id: str) -> None:
    _require_admin(lobby, admin_device_id)

    if lobby.state != LobbyState.OPEN:
        raise ValueError("Lobby is not in a startable state")

    lobby.state = LobbyState.MEASUREMENT_RUNNING
    await _append_event(session, lobby.id, "measurement_started", {"admin_device_id": admin_device_id})


async def share_room_snapshot(
    session: AsyncSession,
    *,
    lobby: Lobby,
    admin_device_id: str,
    room: dict,
) -> None:
    _require_admin(lobby, admin_device_id)
    if not isinstance(room, dict):
        raise ValueError("room payload must be an object")

    await _append_event(
        session,
        lobby.id,
        "room_snapshot",
        {"admin_device_id": admin_device_id},
    )

    payload = {
        "lobby_id": lobby.id,
        "room": room,
        "source_device_id": admin_device_id,
        "shared_at": datetime.utcnow().isoformat(),
    }

    await _broadcast_room_snapshot(
        session,
        lobby.id,
        payload,
        exclude_device_id=admin_device_id,
    )


async def get_events(session: AsyncSession, *, lobby_id: str, after_id: int | None) -> list[LobbyEvent]:
    stmt: Select = select(LobbyEvent).where(LobbyEvent.lobby_id == lobby_id)
    if after_id is not None:
        stmt = stmt.where(LobbyEvent.id > after_id)
    stmt = stmt.order_by(LobbyEvent.id.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def broadcast_step_update(
    session: AsyncSession,
    *,
    lobby: Lobby,
    admin_device_id: str,
    step_index: int,
) -> None:
    """
    Broadcast timeline step update to all lobby participants.
    
    This keeps all clients synchronized on the current measurement timeline step
    (e.g., "construct wall", "furnish room", "place devices", etc.).
    
    Args:
        session: Database session
        lobby: The lobby instance
        admin_device_id: Device ID of the admin making the change
        step_index: The current timeline step index
    """
    _require_admin(lobby, admin_device_id)
    
    await _append_event(
        session,
        lobby.id,
        "step_update",
        {"admin_device_id": admin_device_id, "step_index": step_index},
    )
    
    # Broadcast to all participants except the sender
    participants = await list_participants(session, lobby.id)
    device_ids = [
        p.device_id
        for p in participants
        if p.status == ParticipantStatus.JOINED and p.device_id != admin_device_id
    ]
    
    if device_ids:
        await broadcast_to_devices(
            device_ids,
            "lobby.step_update",
            {
                "lobby_id": lobby.id,
                "step_index": step_index,
                "source_device_id": admin_device_id,
            },
        )


async def broadcast_profile_update(
    session: AsyncSession,
    *,
    lobby: Lobby,
    admin_device_id: str,
    profile_id: str,
) -> None:
    """
    Broadcast measurement profile update to all lobby participants.
    
    This keeps all clients synchronized on the current measurement profile
    (e.g., "smartphone" or "high_end").
    
    Args:
        session: Database session
        lobby: The lobby instance
        admin_device_id: Device ID of the admin making the change
        profile_id: The profile identifier (e.g., "smartphone", "high_end")
    """
    _require_admin(lobby, admin_device_id)
    
    await _append_event(
        session,
        lobby.id,
        "profile_update",
        {"admin_device_id": admin_device_id, "profile_id": profile_id},
    )
    
    # Broadcast to all participants except the sender
    participants = await list_participants(session, lobby.id)
    device_ids = [
        p.device_id
        for p in participants
        if p.status == ParticipantStatus.JOINED and p.device_id != admin_device_id
    ]
    
    if device_ids:
        await broadcast_to_devices(
            device_ids,
            "lobby.profile_update",
            {
                "lobby_id": lobby.id,
                "profile_id": profile_id,
                "source_device_id": admin_device_id,
            },
        )