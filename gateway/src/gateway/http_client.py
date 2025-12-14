from __future__ import annotations

from typing import Any

import httpx


class ServiceHttpClient:
    def __init__(self, *, timeout_seconds: float) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    async def close(self) -> None:
        await self._client.aclose()

    async def post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, Any]:
        resp = await self._client.post(url, json=payload)
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            return resp.status_code, resp.json()
        return resp.status_code, {"text": resp.text}
