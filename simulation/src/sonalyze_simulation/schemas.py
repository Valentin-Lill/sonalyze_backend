from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class MaterialSpec(BaseModel):
    absorption: float = Field(ge=0.0, le=1.0, description="Absorption coefficient (0..1)")
    scattering: float = Field(default=0.0, ge=0.0, le=1.0, description="Scattering coefficient (0..1)")


class ShoeboxRoomSpec(BaseModel):
    type: Literal["shoebox"] = "shoebox"
    dimensions_m: list[float] = Field(
        min_length=3,
        max_length=3,
        description="[length, width, height] in meters",
    )
    wall_materials: dict[
        Literal["west", "east", "south", "north", "floor", "ceiling"], MaterialSpec
    ] = Field(
        default_factory=dict,
        description="Optional per-wall materials. Missing walls use default_material.",
    )
    default_material: MaterialSpec = Field(default_factory=lambda: MaterialSpec(absorption=0.2))


class PolygonRoomSpec(BaseModel):
    type: Literal["polygon"] = "polygon"
    corners_m: list[list[float]] = Field(
        min_length=3,
        description="2D polygon corners [[x,y], ...] in meters (clockwise or counterclockwise)",
    )
    height_m: float = Field(gt=0.0, description="Room height in meters")
    wall_material: MaterialSpec = Field(default_factory=lambda: MaterialSpec(absorption=0.2))
    floor_material: MaterialSpec = Field(default_factory=lambda: MaterialSpec(absorption=0.2))
    ceiling_material: MaterialSpec = Field(default_factory=lambda: MaterialSpec(absorption=0.2))


RoomSpec = Annotated[
    ShoeboxRoomSpec | PolygonRoomSpec,
    Field(discriminator="type"),
]


class SourceSpec(BaseModel):
    id: str
    position_m: list[float] = Field(min_length=3, max_length=3, description="[x,y,z] meters")


class MicrophoneSpec(BaseModel):
    id: str
    position_m: list[float] = Field(min_length=3, max_length=3, description="[x,y,z] meters")


class FurnitureBoxSpec(BaseModel):
    type: Literal["box"] = "box"
    id: str | None = None
    min_m: list[float] = Field(min_length=3, max_length=3, description="[x,y,z] meters")
    max_m: list[float] = Field(min_length=3, max_length=3, description="[x,y,z] meters")
    material: MaterialSpec | None = None


FurnitureSpec = Annotated[FurnitureBoxSpec, Field(discriminator="type")]


class SimulationRequest(BaseModel):
    room: RoomSpec
    sources: list[SourceSpec] = Field(min_length=1)
    microphones: list[MicrophoneSpec] = Field(min_length=1)
    furniture: list[FurnitureSpec] = Field(default_factory=list)

    sample_rate_hz: int = Field(default=16000, gt=0)
    max_order: int = Field(default=12, ge=0)
    air_absorption: bool = Field(default=True)

    rir_duration_s: float = Field(default=2.0, gt=0.0, description="Trim RIRs to this duration")
    include_rir: bool = Field(default=False, description="Include raw RIR arrays in response")


class AcousticMetrics(BaseModel):
    rt60_s: float | None = None
    edt_s: float | None = None
    d50: float | None = None
    c50_db: float | None = None
    c80_db: float | None = None
    drr_db: float | None = None

    sti: float | None = Field(default=None, description="STI if available; may be null")
    sti_method: str | None = None


class PairResult(BaseModel):
    source_id: str
    microphone_id: str
    metrics: AcousticMetrics
    rir: list[float] | None = None
    warnings: list[str] = Field(default_factory=list)


class SimulationResponse(BaseModel):
    sample_rate_hz: int
    pairs: list[PairResult]
    warnings: list[str] = Field(default_factory=list)


class MetricReference(BaseModel):
    key: str = Field(description="Metric identifier that matches simulation response keys", min_length=1)
    label: str = Field(description="Human-friendly metric label", min_length=1)
    unit: str | None = Field(default=None, description="Optional unit displayed alongside the value")
    value: float = Field(description="Target value considered 'good' for this metric")
    min_value: float | None = Field(
        default=None,
        description="Optional lower bound used for chart normalization",
    )
    max_value: float | None = Field(
        default=None,
        description="Optional upper bound used for chart normalization",
    )


class RoomReferenceProfile(BaseModel):
    id: str = Field(description="Stable identifier for the room archetype")
    display_name: str = Field(description="Human friendly room label")
    metrics: list[MetricReference]
    notes: str | None = Field(default=None, description="Optional descriptive copy")


class RoomReferenceProfilesResponse(BaseModel):
    profiles: list[RoomReferenceProfile]


class MaterialInfoResponse(BaseModel):
    """Single material with acoustic properties."""
    id: str = Field(description="Unique identifier for the material")
    display_name: str = Field(description="Human-friendly material name")
    absorption: float = Field(ge=0.0, le=1.0, description="Absorption coefficient")
    scattering: float = Field(ge=0.0, le=1.0, description="Scattering coefficient")


class MaterialsResponse(BaseModel):
    """Response containing all available materials."""
    materials: list[MaterialInfoResponse]
