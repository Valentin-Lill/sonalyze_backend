from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ClientMessage(BaseModel):
    event: str = Field(min_length=1)
    request_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class IdentifyData(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ServerMessage(BaseModel):
    type: Literal["response", "event", "error"]
    event: str
    request_id: str | None = None
    data: Any | None = None
    error: ErrorBody | None = None


class GatewayClientInfo(BaseModel):
    device_id: str
    connection_id: str
    ip: str | None = None


class GatewayForwardRequest(BaseModel):
    client: GatewayClientInfo
    message: ClientMessage


class BroadcastTargets(BaseModel):
    device_ids: list[str] = Field(default_factory=list)


class BroadcastRequest(BaseModel):
    event: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    targets: BroadcastTargets
