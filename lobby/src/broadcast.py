from __future__ import annotations

from typing import Any

import httpx

from settings import settings


async def broadcast_to_lobby(lobby_id: str, event: str, data: dict[str, Any], exclude_device_id: str | None = None) -> None:
    """
    Broadcasts an event to all participants in a lobby via the Gateway.
    
    Note: The Gateway's /internal/broadcast endpoint expects a list of device_ids.
    However, since we don't want to fetch all participants here every time (circular dependency or extra query),
    we might need a way to tell the Gateway "send to everyone in lobby X".
    
    BUT, the Gateway doesn't know about "lobbies". It only knows about "device_ids".
    So we MUST fetch the participants here in the Lobby Service and send the list of device_ids to the Gateway.
    """
    # This function will be called from service.py, where we can pass the list of device_ids.
    pass


async def broadcast_to_devices(device_ids: list[str], event: str, data: dict[str, Any]) -> None:
    if not device_ids:
        return

    url = f"{settings.gateway_url}/internal/broadcast"
    headers = {"X-Internal-Token": settings.internal_auth_token}
    payload = {
        "event": event,
        "data": data,
        "targets": {"device_ids": device_ids},
    }

    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, headers=headers, timeout=5.0)
        except Exception as e:
            print(f"Failed to broadcast event {event}: {e}")
