from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.http_errors import not_found
from app.models import SimulationJob
from app.schemas import SimulationJobCreate, SimulationJobOut, SimulationJobPatch

from ._common import apply_patch

router = APIRouter(tags=["simulation_jobs"])


@router.post("/simulation-jobs", response_model=SimulationJobOut)
async def create_simulation_job(payload: SimulationJobCreate, db: AsyncSession = Depends(get_db)) -> SimulationJob:
    job = SimulationJob(
        requested_by_device_id=payload.requested_by_device_id,
        lobby_id=payload.lobby_id,
        status=payload.status or "queued",
        params=payload.params,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/simulation-jobs", response_model=list[SimulationJobOut])
async def list_simulation_jobs(
    lobby_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[SimulationJob]:
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)

    stmt = select(SimulationJob).order_by(SimulationJob.created_at.desc()).limit(limit).offset(offset)
    if lobby_id is not None:
        stmt = stmt.where(SimulationJob.lobby_id == lobby_id)
    if status is not None:
        stmt = stmt.where(SimulationJob.status == status)

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/simulation-jobs/{job_id}", response_model=SimulationJobOut)
async def get_simulation_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> SimulationJob:
    job = await db.get(SimulationJob, job_id)
    if job is None:
        raise not_found("simulation job")
    return job


@router.patch("/simulation-jobs/{job_id}", response_model=SimulationJobOut)
async def patch_simulation_job(job_id: uuid.UUID, payload: SimulationJobPatch, db: AsyncSession = Depends(get_db)) -> SimulationJob:
    job = await db.get(SimulationJob, job_id)
    if job is None:
        raise not_found("simulation job")

    apply_patch(job, payload)
    await db.commit()
    await db.refresh(job)
    return job


@router.delete("/simulation-jobs/{job_id}")
async def delete_simulation_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    job = await db.get(SimulationJob, job_id)
    if job is None:
        raise not_found("simulation job")

    await db.delete(job)
    await db.commit()
    return {"deleted": True}
