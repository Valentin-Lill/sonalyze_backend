"""Gateway handler for receiving forwarded events from the gateway service."""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from sonalyze_simulation.schemas import SimulationRequest
from sonalyze_simulation.simulate import run_simulation
from sonalyze_simulation.payload_adapter import normalize_simulation_payload


logger = logging.getLogger(__name__)


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
    message: ClientMessage,
) -> dict[str, Any]:
    """Handle simulation.run event."""
    request_id = message.request_id or "unknown"
    logger.info(
        "simulation.run started (request_id=%s, device=%s, connection=%s)",
        request_id,
        client.device_id,
        client.connection_id,
    )
    start_time = time.perf_counter()
    try:
        normalized = normalize_simulation_payload(message.data)
        # Extract raw furniture data for ray tracing (preserves rotation)
        raw_furniture = normalized.pop("raw_furniture", None)
        # Extract use_raytracing flag for experimental raytracing mode
        use_raytracing = bool(message.data.get("use_raytracing", False))
        request = SimulationRequest.model_validate(normalized)
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Invalid simulation request (request_id=%s): %s",
            request_id,
            exc,
        )
        raise HTTPException(status_code=400, detail=f"Invalid simulation request: {exc}") from exc

    try:
        result = run_simulation(request, raw_furniture=raw_furniture, use_raytracing=use_raytracing)
    except Exception:
        logger.exception(
            "Simulation execution failed (request_id=%s)",
            request_id,
        )
        raise

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    logger.info(
        "simulation.run completed in %.0f ms (request_id=%s, room=%s, sources=%d, microphones=%d)",
        elapsed_ms,
        request_id,
        request.room.__class__.__name__,
        len(request.sources),
        len(request.microphones),
    )
    return result.model_dump(mode="json")


def _handle_simulation_health(
    _client: GatewayClientInfo,
    _message: ClientMessage,
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
        logger.warning(
            "Unknown gateway event '%s' (request_id=%s, device=%s)",
            event,
            request.message.request_id,
            request.client.device_id,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event: {event}"
        )
    
    try:
        logger.info(
            "Gateway event '%s' received (request_id=%s, device=%s, connection=%s)",
            event,
            request.message.request_id,
            request.client.device_id,
            request.client.connection_id,
        )
        response = handler(request.client, request.message)
        logger.info(
            "Gateway event '%s' succeeded (request_id=%s)",
            event,
            request.message.request_id,
        )
        return response
    except HTTPException as exc:
        logger.warning(
            "Gateway event '%s' failed with HTTP %s (request_id=%s): %s",
            event,
            exc.status_code,
            request.message.request_id,
            exc.detail,
        )
        raise
    except Exception as exc:
        logger.exception(
            "Gateway event '%s' failed unexpectedly (request_id=%s)",
            event,
            request.message.request_id,
        )
        raise HTTPException(status_code=500, detail=str(exc))
