from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.http_errors import not_found
from app.models import Device
from app.schemas import DeviceCreate, DeviceOut, DevicePatch

router = APIRouter(tags=["devices"])


@router.post("/devices", response_model=DeviceOut)
async def upsert_device(payload: DeviceCreate, db: AsyncSession = Depends(get_db)) -> Device:
    stmt = (
        insert(Device)
        .values(
            external_id=payload.external_id,
            label=payload.label,
            platform=payload.platform,
            meta=payload.meta,
        )
        .on_conflict_do_update(
            index_elements=[Device.external_id],
            set_={
                "label": payload.label,
                "platform": payload.platform,
                "meta": payload.meta,
            },
        )
        .returning(Device)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()


@router.get("/devices", response_model=list[DeviceOut])
async def list_devices(limit: int = 100, offset: int = 0, db: AsyncSession = Depends(get_db)) -> list[Device]:
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)
    result = await db.execute(select(Device).order_by(Device.created_at.desc()).limit(limit).offset(offset))
    return list(result.scalars().all())


@router.get("/devices/{device_id}", response_model=DeviceOut)
async def get_device(device_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Device:
    device = await db.get(Device, device_id)
    if device is None:
        raise not_found("device")
    return device


@router.get("/devices/by-external/{external_id}", response_model=DeviceOut)
async def get_device_by_external_id(external_id: str, db: AsyncSession = Depends(get_db)) -> Device:
    result = await db.execute(select(Device).where(Device.external_id == external_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise not_found("device")
    return device


@router.patch("/devices/{device_id}", response_model=DeviceOut)
async def patch_device(device_id: uuid.UUID, payload: DevicePatch, db: AsyncSession = Depends(get_db)) -> Device:
    device = await db.get(Device, device_id)
    if device is None:
        raise not_found("device")

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(device, key, value)

    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/devices/{device_id}")
async def delete_device(device_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    device = await db.get(Device, device_id)
    if device is None:
        raise not_found("device")

    await db.delete(device)
    await db.commit()
    return {"deleted": True}
