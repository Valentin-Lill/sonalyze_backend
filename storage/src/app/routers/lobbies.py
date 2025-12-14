from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.http_errors import not_found
from app.models import Lobby
from app.schemas import LobbyCreate, LobbyOut, LobbyPatch
from app.utils import generate_lobby_code

from ._common import apply_patch, map_integrity_error

router = APIRouter(tags=["lobbies"])


@router.post("/lobbies", response_model=LobbyOut)
async def create_lobby(payload: LobbyCreate, db: AsyncSession = Depends(get_db)) -> Lobby:
    code = payload.code
    if code is None or code.strip() == "":
        code = generate_lobby_code()

    lobby = Lobby(
        code=code,
        state=payload.state or "created",
        creator_device_id=payload.creator_device_id,
    )

    db.add(lobby)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise map_integrity_error(exc)

    await db.refresh(lobby)
    return lobby


@router.get("/lobbies", response_model=list[LobbyOut])
async def list_lobbies(limit: int = 100, offset: int = 0, db: AsyncSession = Depends(get_db)) -> list[Lobby]:
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)
    result = await db.execute(select(Lobby).order_by(Lobby.created_at.desc()).limit(limit).offset(offset))
    return list(result.scalars().all())


@router.get("/lobbies/{lobby_id}", response_model=LobbyOut)
async def get_lobby(lobby_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Lobby:
    lobby = await db.get(Lobby, lobby_id)
    if lobby is None:
        raise not_found("lobby")
    return lobby


@router.get("/lobbies/by-code/{code}", response_model=LobbyOut)
async def get_lobby_by_code(code: str, db: AsyncSession = Depends(get_db)) -> Lobby:
    result = await db.execute(select(Lobby).where(Lobby.code == code))
    lobby = result.scalar_one_or_none()
    if lobby is None:
        raise not_found("lobby")
    return lobby


@router.patch("/lobbies/{lobby_id}", response_model=LobbyOut)
async def patch_lobby(lobby_id: uuid.UUID, payload: LobbyPatch, db: AsyncSession = Depends(get_db)) -> Lobby:
    lobby = await db.get(Lobby, lobby_id)
    if lobby is None:
        raise not_found("lobby")

    apply_patch(lobby, payload)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise map_integrity_error(exc)

    await db.refresh(lobby)
    return lobby


@router.delete("/lobbies/{lobby_id}")
async def delete_lobby(lobby_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    lobby = await db.get(Lobby, lobby_id)
    if lobby is None:
        raise not_found("lobby")

    await db.delete(lobby)
    await db.commit()
    return {"deleted": True}
