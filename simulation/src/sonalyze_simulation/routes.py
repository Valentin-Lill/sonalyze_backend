from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from sonalyze_simulation.schemas import (
    MaterialsResponse,
    RoomReferenceProfilesResponse,
    SimulationRequest,
    SimulationResponse,
)
from sonalyze_simulation.simulate import run_simulation
from sonalyze_simulation.payload_adapter import normalize_simulation_payload
from sonalyze_simulation.reference_profiles import get_reference_profiles
from sonalyze_simulation.materials import get_all_materials

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/simulate", response_model=SimulationResponse)
def simulate(raw_request: dict[str, Any] = Body(...)) -> SimulationResponse:
    try:
        normalized = normalize_simulation_payload(raw_request)
        # Extract raw furniture data for ray tracing (preserves rotation)
        raw_furniture = normalized.pop("raw_furniture", None)
        # Extract use_raytracing flag for experimental raytracing mode
        use_raytracing = bool(raw_request.get("use_raytracing", False))
        request = SimulationRequest.model_validate(normalized)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid simulation request: {exc}") from exc
    return run_simulation(request, raw_furniture=raw_furniture, use_raytracing=use_raytracing)


@router.get("/reference-profiles", response_model=RoomReferenceProfilesResponse)
def reference_profiles() -> RoomReferenceProfilesResponse:
    profiles = get_reference_profiles()
    return RoomReferenceProfilesResponse(profiles=profiles)


@router.get("/materials", response_model=MaterialsResponse)
def materials() -> MaterialsResponse:
    """Return all available acoustic materials for room simulation."""
    all_materials = get_all_materials()
    return MaterialsResponse(
        materials=[
            {
                "id": m.id,
                "display_name": m.display_name,
                "absorption": m.absorption,
                "scattering": m.scattering,
            }
            for m in all_materials
        ]
    )
