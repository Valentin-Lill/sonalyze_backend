from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.http_errors import not_found
from app.models import Participant
from app.schemas import ParticipantCreate, ParticipantOut, ParticipantPatch

from ._common import apply_patch, map_integrity_error

router = APIRouter(tags=["participants"])


@router.post("/participants", response_model=ParticipantOut)
async def create_participant(payload: ParticipantCreate, db: AsyncSession = Depends(get_db)) -> Participant:
    participant = Participant(
        lobby_id=payload.lobby_id,
        device_id=payload.device_id,
        role=payload.role or "observer",
        status=payload.status or "connected",
    )
    db.add(participant)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise map_integrity_error(exc)

    await db.refresh(participant)
    return participant


@router.get("/participants", response_model=list[ParticipantOut])
async def list_participants(
    lobby_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[Participant]:
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)

    stmt = select(Participant).order_by(Participant.joined_at.desc()).limit(limit).offset(offset)
    if lobby_id is not None:
        stmt = stmt.where(Participant.lobby_id == lobby_id)
    if device_id is not None:
        stmt = stmt.where(Participant.device_id == device_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/participants/{participant_id}", response_model=ParticipantOut)
async def get_participant(participant_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Participant:
    participant = await db.get(Participant, participant_id)
    if participant is None:
        raise not_found("participant")
    return participant


@router.patch("/participants/{participant_id}", response_model=ParticipantOut)
async def patch_participant(
    participant_id: uuid.UUID, payload: ParticipantPatch, db: AsyncSession = Depends(get_db)
) -> Participant:
    participant = await db.get(Participant, participant_id)
    if participant is None:
        raise not_found("participant")

    apply_patch(participant, payload)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise map_integrity_error(exc)

    await db.refresh(participant)
    return participant


@router.delete("/participants/{participant_id}")
async def delete_participant(participant_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    participant = await db.get(Participant, participant_id)
    if participant is None:
        raise not_found("participant")

    await db.delete(participant)
    await db.commit()
    return {"deleted": True}
