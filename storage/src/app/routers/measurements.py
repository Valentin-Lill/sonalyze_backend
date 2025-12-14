from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.http_errors import not_found
from app.models import Measurement
from app.schemas import MeasurementCreate, MeasurementOut, MeasurementPatch

from ._common import apply_patch

router = APIRouter(tags=["measurements"])


@router.post("/measurements", response_model=MeasurementOut)
async def create_measurement(payload: MeasurementCreate, db: AsyncSession = Depends(get_db)) -> Measurement:
    measurement = Measurement(
        lobby_id=payload.lobby_id,
        created_by_device_id=payload.created_by_device_id,
        kind=payload.kind or "raw",
        sample_rate_hz=payload.sample_rate_hz,
        channels=payload.channels,
        raw_blob_ref=payload.raw_blob_ref,
        raw_bytes=payload.raw_bytes,
        raw_sha256=payload.raw_sha256,
        meta=payload.meta,
        started_at=payload.started_at,
        stopped_at=payload.stopped_at,
    )

    db.add(measurement)
    await db.commit()
    await db.refresh(measurement)
    return measurement


@router.get("/measurements", response_model=list[MeasurementOut])
async def list_measurements(
    lobby_id: uuid.UUID | None = None,
    created_by_device_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[Measurement]:
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)

    stmt = select(Measurement).order_by(Measurement.created_at.desc()).limit(limit).offset(offset)
    if lobby_id is not None:
        stmt = stmt.where(Measurement.lobby_id == lobby_id)
    if created_by_device_id is not None:
        stmt = stmt.where(Measurement.created_by_device_id == created_by_device_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/measurements/{measurement_id}", response_model=MeasurementOut)
async def get_measurement(measurement_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Measurement:
    measurement = await db.get(Measurement, measurement_id)
    if measurement is None:
        raise not_found("measurement")
    return measurement


@router.patch("/measurements/{measurement_id}", response_model=MeasurementOut)
async def patch_measurement(
    measurement_id: uuid.UUID, payload: MeasurementPatch, db: AsyncSession = Depends(get_db)
) -> Measurement:
    measurement = await db.get(Measurement, measurement_id)
    if measurement is None:
        raise not_found("measurement")

    apply_patch(measurement, payload)
    await db.commit()
    await db.refresh(measurement)
    return measurement


@router.delete("/measurements/{measurement_id}")
async def delete_measurement(measurement_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    measurement = await db.get(Measurement, measurement_id)
    if measurement is None:
        raise not_found("measurement")

    await db.delete(measurement)
    await db.commit()
    return {"deleted": True}
