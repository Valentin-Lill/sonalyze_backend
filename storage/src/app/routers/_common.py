from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError


def conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def map_integrity_error(exc: IntegrityError, default_detail: str = "conflict") -> HTTPException:
    message = str(getattr(exc, "orig", exc))
    detail = default_detail

    if "uq_participant_lobby_device" in message:
        detail = "participant already exists for lobby/device"
    elif "devices_external_id_key" in message or "devices.external_id" in message:
        detail = "device external_id already exists"
    elif "lobbies_code_key" in message or "lobbies.code" in message:
        detail = "lobby code already exists"

    return conflict(detail)


def apply_patch(model_obj: Any, patch_obj: Any) -> None:
    data = patch_obj.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(model_obj, key, value)
