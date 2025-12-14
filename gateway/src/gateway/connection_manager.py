from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from gateway.rate_limit import TokenBucket


@dataclass
class Connection:
    connection_id: str
    websocket: WebSocket
    ip: str | None
    rate_limiter: TokenBucket
    device_id: str | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections_by_id: dict[str, Connection] = {}
        self._connections_by_device: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        websocket: WebSocket,
        *,
        device_id: str | None,
        ip: str | None,
        rate_limiter: TokenBucket,
    ) -> Connection:
        connection_id = secrets.token_urlsafe(16)
        conn = Connection(
            connection_id=connection_id,
            websocket=websocket,
            device_id=device_id,
            ip=ip,
            rate_limiter=rate_limiter,
        )
        async with self._lock:
            self._connections_by_id[connection_id] = conn
            if device_id:
                self._connections_by_device.setdefault(device_id, set()).add(connection_id)
        return conn

    async def bind_device_id(self, conn: Connection, device_id: str) -> None:
        async with self._lock:
            conn.device_id = device_id
            self._connections_by_device.setdefault(device_id, set()).add(conn.connection_id)

    async def unregister(self, connection_id: str) -> None:
        async with self._lock:
            conn = self._connections_by_id.pop(connection_id, None)
            if not conn:
                return
            if conn.device_id:
                ids = self._connections_by_device.get(conn.device_id)
                if ids:
                    ids.discard(connection_id)
                    if not ids:
                        self._connections_by_device.pop(conn.device_id, None)

    async def send_json(self, conn: Connection, payload: Any) -> None:
        async with conn.send_lock:
            await conn.websocket.send_json(payload)

    async def send_to_device_ids(self, device_ids: list[str], payload: Any) -> int:
        sent = 0
        to_send: list[Connection] = []
        async with self._lock:
            for device_id in device_ids:
                for connection_id in self._connections_by_device.get(device_id, set()):
                    conn = self._connections_by_id.get(connection_id)
                    if conn:
                        to_send.append(conn)

        for conn in to_send:
            try:
                await self.send_json(conn, payload)
                sent += 1
            except Exception:
                # Best-effort fan-out; dead sockets are cleaned up by ws loop
                pass
        return sent
