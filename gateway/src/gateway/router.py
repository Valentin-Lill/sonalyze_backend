from __future__ import annotations

from typing import Any

import httpx

from gateway.config import Settings
from gateway.http_client import ServiceHttpClient
from gateway.models import ClientMessage, GatewayForwardRequest, GatewayClientInfo


# Measurement session management events that should go to lobby service
# These are stateful events that manage measurement coordination
MEASUREMENT_SESSION_EVENTS = {
    "measurement.create_session",
    "measurement.start_speaker",
    "measurement.session_status",
    "measurement.cancel_session",
    "measurement.broadcast_results",
    "measurement.ready",
    "measurement.client_ready",
    "measurement.speaker_audio_ready",
    "measurement.recording_started",
    "measurement.playback_complete",
    "measurement.speaker_finished",
    "measurement.recording_uploaded",
    "measurement.error",
}

# Stateless measurement events that should go to measurement service
# These are pure computation events with no state management
MEASUREMENT_STATELESS_EVENTS = {
    "measurement.create_job",
    "measurement.get_job",
    "measurement.get_audio_info",
    "analysis.run",
}


class EventRouter:
    def __init__(self, settings: Settings, http: ServiceHttpClient) -> None:
        self._settings = settings
        self._http = http

    def _service_url_for_event(self, event: str) -> str | None:
        # Lobby events
        if event.startswith("lobby.") or event.startswith("role."):
            return self._settings.lobby_url
        
        # Measurement session events go to lobby (stateful)
        if event in MEASUREMENT_SESSION_EVENTS:
            return self._settings.lobby_url
        
        # Stateless measurement/analysis events go to measurement service
        if event in MEASUREMENT_STATELESS_EVENTS:
            return self._settings.measurement_url
        
        # Fallback for any other measurement.* events - route to lobby for session management
        if event.startswith("measurement."):
            return self._settings.lobby_url
        
        # Analysis events go to measurement service
        if event.startswith("analysis."):
            return self._settings.measurement_url
        
        # Simulation events
        if event.startswith("simulation."):
            return self._settings.simulation_url
        
        if event == "identify":
            return None
        
        return None

    async def forward(self, *, client: GatewayClientInfo, message: ClientMessage) -> Any:
        service_url = self._service_url_for_event(message.event)
        if not service_url:
            raise ValueError(f"Unknown event '{message.event}'")

        url = f"{service_url}/gateway/handle"
        req = GatewayForwardRequest(client=client, message=message)

        print(f"[router] Forwarding event '{message.event}' to {url}")
        print(f"[router] Request payload: {req.model_dump()}")

        try:
            status, body = await self._http.post_json(url, req.model_dump())
        except httpx.TimeoutException as exc:
            print(f"[router] Upstream timeout for {url}")
            raise RuntimeError("Upstream timeout") from exc
        except httpx.RequestError as exc:
            print(f"[router] Upstream unreachable for {url}: {exc}")
            raise RuntimeError("Upstream unreachable") from exc

        print(f"[router] Response status={status}, body={body}")

        if status >= 400:
            error_detail = body.get("detail", str(body)) if isinstance(body, dict) else str(body)
            print(f"[router] Upstream error ({status}): {error_detail}")
            raise RuntimeError(f"Upstream error ({status}): {error_detail}")
        return body
