from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from sonalyze_simulation.schemas import (
    RoomReferenceProfilesResponse,
    SimulationRequest,
    SimulationResponse,
)
from sonalyze_simulation.simulate import run_simulation
from sonalyze_simulation.payload_adapter import normalize_simulation_payload
from sonalyze_simulation.reference_profiles import get_reference_profiles

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/simulate", response_model=SimulationResponse)
def simulate(raw_request: dict[str, Any] = Body(...)) -> SimulationResponse:
    try:
        normalized = normalize_simulation_payload(raw_request)
        request = SimulationRequest.model_validate(normalized)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid simulation request: {exc}") from exc
    return run_simulation(request)


@router.get("/reference-profiles", response_model=RoomReferenceProfilesResponse)
def reference_profiles() -> RoomReferenceProfilesResponse:
    profiles = get_reference_profiles()
    return RoomReferenceProfilesResponse(profiles=profiles)
