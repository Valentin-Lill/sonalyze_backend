from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RoomModel(BaseModel):
    # 2D polygon vertices (x,y) in meters, counter-clockwise recommended
    vertices: list[tuple[float, float]] = Field(default_factory=list)
    height_m: float | None = None


class PositionedEntity(BaseModel):
    id: str
    position: tuple[float, float, float]


class MapModel(BaseModel):
    room: RoomModel | None = None
    furniture: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[PositionedEntity] = Field(default_factory=list)
    receivers: list[PositionedEntity] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class CreateJobRequest(BaseModel):
    map: MapModel
    meta: dict[str, Any] = Field(default_factory=dict)


class CreateJobResponse(BaseModel):
    job_id: str


class AnalyzeRequest(BaseModel):
    source: Literal["impulse_response", "sweep_deconvolution"]
    sweep_reference_upload: str | None = None
    recording_upload: str | None = None
    impulse_response_upload: str | None = None


class AnalyzeResponse(BaseModel):
    job_id: str
    results: dict[str, Any]
