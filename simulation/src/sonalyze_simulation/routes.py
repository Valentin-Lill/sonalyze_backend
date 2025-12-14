from __future__ import annotations

from fastapi import APIRouter

from sonalyze_simulation.schemas import SimulationRequest, SimulationResponse
from sonalyze_simulation.simulate import run_simulation

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/simulate", response_model=SimulationResponse)
def simulate(request: SimulationRequest) -> SimulationResponse:
    return run_simulation(request)
