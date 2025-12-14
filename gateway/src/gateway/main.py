from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect

from gateway.config import settings
from gateway.connection_manager import ConnectionManager
from gateway.http_client import ServiceHttpClient
from gateway.models import (
    BroadcastRequest,
    ClientMessage,
    ErrorBody,
    IdentifyData,
    ServerMessage,
    GatewayClientInfo,
)
from gateway.rate_limit import TokenBucket
from gateway.router import EventRouter


@asynccontextmanager
async def lifespan(app: FastAPI):
    http = ServiceHttpClient(timeout_seconds=settings.http_timeout_seconds)
    app.state.http = http
    app.state.router = EventRouter(settings, http)
    app.state.connections = ConnectionManager()
    yield
    await http.close()


app = FastAPI(title="sonalyze-gateway", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _error(event: str, request_id: str | None, code: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return ServerMessage(
        type="error",
        event=event,
        request_id=request_id,
        error=ErrorBody(code=code, message=message, details=details),
    ).model_dump()


@app.post("/internal/broadcast")
async def internal_broadcast(payload: BroadcastRequest, x_internal_token: str | None = Header(default=None)) -> dict[str, Any]:
    if not settings.internal_auth_token:
        raise HTTPException(status_code=500, detail="INTERNAL_AUTH_TOKEN not configured")
    if x_internal_token != settings.internal_auth_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    msg = ServerMessage(type="event", event=payload.event, data=payload.data).model_dump()
    manager: ConnectionManager = app.state.connections
    sent = await manager.send_to_device_ids(payload.targets.device_ids, msg)
    return {"sent": sent}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, device_id: str | None = Query(default=None)) -> None:
    await websocket.accept()

    ip = websocket.client.host if websocket.client else None
    manager: ConnectionManager = app.state.connections

    limiter = TokenBucket(rate_per_second=settings.rate_limit_rps, capacity=settings.rate_limit_burst)
    conn = await manager.register(websocket, device_id=device_id, ip=ip, rate_limiter=limiter)

    try:
        if not conn.device_id:
            await manager.send_json(
                conn,
                ServerMessage(type="event", event="gateway.identify_required", data={"hint": "Send {event:'identify', data:{device_id}} or connect with ?device_id="}).model_dump(),
            )

        while True:
            raw = await websocket.receive_text()

            if len(raw.encode("utf-8")) > settings.max_message_bytes:
                await manager.send_json(conn, _error("gateway", None, "message_too_large", "Message exceeds MAX_MESSAGE_BYTES"))
                continue

            if not conn.rate_limiter.allow(1.0):
                await manager.send_json(conn, _error("gateway", None, "rate_limited", "Too many messages"))
                continue

            try:
                data = json.loads(raw)
                msg = ClientMessage.model_validate(data)
            except Exception:
                await manager.send_json(conn, _error("gateway", None, "bad_request", "Invalid JSON message"))
                continue

            if conn.device_id is None:
                if msg.event != "identify":
                    await manager.send_json(conn, _error(msg.event, msg.request_id, "unauthenticated", "Identify first"))
                    continue
                try:
                    ident = IdentifyData.model_validate(msg.data)
                except Exception:
                    await manager.send_json(conn, _error(msg.event, msg.request_id, "bad_request", "identify requires data.device_id"))
                    continue

                await manager.bind_device_id(conn, ident.device_id)
                await manager.send_json(
                    conn,
                    ServerMessage(type="response", event="identify", request_id=msg.request_id, data={"device_id": ident.device_id}).model_dump(),
                )
                continue

            router: EventRouter = app.state.router
            client_info = GatewayClientInfo(device_id=conn.device_id, connection_id=conn.connection_id, ip=conn.ip)

            try:
                body = await router.forward(client=client_info, message=msg)
                await manager.send_json(
                    conn,
                    ServerMessage(type="response", event=msg.event, request_id=msg.request_id, data=body).model_dump(),
                )
            except ValueError as exc:
                await manager.send_json(conn, _error(msg.event, msg.request_id, "unknown_event", str(exc)))
            except RuntimeError as exc:
                await manager.send_json(conn, _error(msg.event, msg.request_id, "upstream_error", str(exc)))

    except WebSocketDisconnect:
        pass
    finally:
        await manager.unregister(conn.connection_id)
