"""Gateway handler for receiving forwarded events from the gateway service."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from sonalyze_simulation.schemas import SimulationRequest
from sonalyze_simulation.simulate import run_simulation
from sonalyze_simulation.payload_adapter import normalize_simulation_payload


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


def _handle_simulation_run(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Handle simulation.run event."""
    try:
        normalized = normalize_simulation_payload(data)
        request = SimulationRequest.model_validate(normalized)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid simulation request: {exc}") from exc
    
    result = run_simulation(request)
    return result.model_dump(mode="json")


def _handle_simulation_health(
    client: GatewayClientInfo,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Handle simulation.health event."""
    return {"status": "ok"}


# Event handlers mapping
EVENT_HANDLERS = {
    "simulation.run": _handle_simulation_run,
    "simulation.health": _handle_simulation_health,
}


@router.post("/gateway/handle")
def gateway_handle(request: GatewayForwardRequest) -> dict[str, Any]:
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
        return handler(request.client, request.message.data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
