from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class APIModel(BaseModel):
    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }


# --- Devices ---
class DeviceCreate(APIModel):
    external_id: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=256)
    platform: str | None = Field(default=None, max_length=64)
    meta: dict = Field(default_factory=dict, alias="metadata")


class DevicePatch(APIModel):
    label: str | None = Field(default=None, max_length=256)
    platform: str | None = Field(default=None, max_length=64)
    meta: dict | None = Field(default=None, alias="metadata")


class DeviceOut(APIModel):
    id: uuid.UUID
    external_id: str
    label: str | None
    platform: str | None
    meta: dict = Field(alias="metadata")
    created_at: datetime


# --- Lobbies ---
class LobbyCreate(APIModel):
    code: str | None = Field(default=None, max_length=16)
    state: str | None = Field(default=None, max_length=32)
    creator_device_id: uuid.UUID | None = None


class LobbyPatch(APIModel):
    code: str | None = Field(default=None, max_length=16)
    state: str | None = Field(default=None, max_length=32)
    creator_device_id: uuid.UUID | None = None


class LobbyOut(APIModel):
    id: uuid.UUID
    code: str
    state: str
    creator_device_id: uuid.UUID | None
    created_at: datetime


# --- Participants ---
class ParticipantCreate(APIModel):
    lobby_id: uuid.UUID
    device_id: uuid.UUID
    role: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)


class ParticipantPatch(APIModel):
    role: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)


class ParticipantOut(APIModel):
    id: uuid.UUID
    lobby_id: uuid.UUID
    device_id: uuid.UUID
    role: str
    status: str
    joined_at: datetime


# --- Measurements ---
class MeasurementCreate(APIModel):
    lobby_id: uuid.UUID | None = None
    created_by_device_id: uuid.UUID | None = None
    kind: str | None = Field(default=None, max_length=64)
    sample_rate_hz: int | None = Field(default=None, ge=1)
    channels: int | None = Field(default=None, ge=1)

    raw_blob_ref: str | None = None
    raw_bytes: int | None = Field(default=None, ge=0)
    raw_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    meta: dict = Field(default_factory=dict, alias="metadata")
    started_at: datetime | None = None
    stopped_at: datetime | None = None


class MeasurementPatch(APIModel):
    kind: str | None = Field(default=None, max_length=64)
    sample_rate_hz: int | None = Field(default=None, ge=1)
    channels: int | None = Field(default=None, ge=1)

    raw_blob_ref: str | None = None
    raw_bytes: int | None = Field(default=None, ge=0)
    raw_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    meta: dict | None = Field(default=None, alias="metadata")
    started_at: datetime | None = None
    stopped_at: datetime | None = None


class MeasurementOut(APIModel):
    id: uuid.UUID
    lobby_id: uuid.UUID | None
    created_by_device_id: uuid.UUID | None

    kind: str
    sample_rate_hz: int | None
    channels: int | None

    raw_blob_ref: str | None
    raw_bytes: int | None
    raw_sha256: str | None

    meta: dict = Field(alias="metadata")
    started_at: datetime | None
    stopped_at: datetime | None
    created_at: datetime


# --- Analysis outputs ---
class AnalysisOutputCreate(APIModel):
    measurement_id: uuid.UUID
    type: str = Field(min_length=1, max_length=64)
    status: str | None = Field(default=None, max_length=32)
    result: dict = Field(default_factory=dict)


class AnalysisOutputPatch(APIModel):
    status: str | None = Field(default=None, max_length=32)
    result: dict | None = None


class AnalysisOutputOut(APIModel):
    id: uuid.UUID
    measurement_id: uuid.UUID
    type: str
    status: str
    result: dict
    created_at: datetime


# --- Simulation jobs ---
class SimulationJobCreate(APIModel):
    requested_by_device_id: uuid.UUID | None = None
    lobby_id: uuid.UUID | None = None
    status: str | None = Field(default=None, max_length=32)
    params: dict = Field(default_factory=dict)


class SimulationJobPatch(APIModel):
    status: str | None = Field(default=None, max_length=32)
    params: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class SimulationJobOut(APIModel):
    id: uuid.UUID
    requested_by_device_id: uuid.UUID | None
    lobby_id: uuid.UUID | None
    status: str
    params: dict
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


# --- Simulation results ---
class SimulationResultCreate(APIModel):
    job_id: uuid.UUID
    result: dict = Field(default_factory=dict)


class SimulationResultPatch(APIModel):
    result: dict | None = None


class SimulationResultOut(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    result: dict
    created_at: datetime
