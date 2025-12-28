from __future__ import annotations

from typing import Any

import httpx

from gateway.config import Settings
from gateway.http_client import ServiceHttpClient
from gateway.models import ClientMessage, GatewayForwardRequest, GatewayClientInfo


class EventRouter:
    def __init__(self, settings: Settings, http: ServiceHttpClient) -> None:
        self._settings = settings
        self._http = http

    def _service_url_for_event(self, event: str) -> str | None:
        if event.startswith("lobby.") or event.startswith("role."):
            return self._settings.lobby_url
        if event.startswith("measurement.") or event.startswith("analysis."):
            return self._settings.measurement_url
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
