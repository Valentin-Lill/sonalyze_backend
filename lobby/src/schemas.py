from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from models import LobbyState, ParticipantRole, ParticipantStatus


class HealthResponse(BaseModel):
    service: str
    ok: bool


class LobbyCreateRequest(BaseModel):
    creator_device_id: str = Field(min_length=1, max_length=128)


class LobbyCreateResponse(BaseModel):
    lobby_id: str
    code: str
    admin_device_id: str
    state: LobbyState


class LobbyJoinRequest(BaseModel):
    code: str = Field(min_length=4, max_length=16)
    device_id: str = Field(min_length=1, max_length=128)


class LobbyLeaveRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)


class AssignRoleRequest(BaseModel):
    admin_device_id: str = Field(min_length=1, max_length=128)
    target_device_id: str = Field(min_length=1, max_length=128)
    role: ParticipantRole


class StartMeasurementRequest(BaseModel):
    admin_device_id: str = Field(min_length=1, max_length=128)


class ParticipantOut(BaseModel):
    device_id: str
    role: ParticipantRole
    status: ParticipantStatus
    joined_at: datetime
    left_at: datetime | None


class LobbyOut(BaseModel):
    lobby_id: str
    code: str
    admin_device_id: str
    state: LobbyState
    participants: list[ParticipantOut]


class EventOut(BaseModel):
    id: int
    type: str
    payload: dict
    created_at: datetime


class EventsResponse(BaseModel):
    lobby_id: str
    events: list[EventOut]


EventType = Literal[
    "lobby_created",
    "participant_joined",
    "participant_left",
    "role_assigned",
    "measurement_started",
]
