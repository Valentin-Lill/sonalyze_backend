from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.http_errors import not_found
from app.models import SimulationResult
from app.schemas import SimulationResultCreate, SimulationResultOut, SimulationResultPatch

from ._common import apply_patch, map_integrity_error

router = APIRouter(tags=["simulation_results"])


@router.post("/simulation-results", response_model=SimulationResultOut)
async def create_simulation_result(payload: SimulationResultCreate, db: AsyncSession = Depends(get_db)) -> SimulationResult:
    result_row = SimulationResult(job_id=payload.job_id, result=payload.result)
    db.add(result_row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise map_integrity_error(exc, default_detail="simulation result already exists for job")

    await db.refresh(result_row)
    return result_row


@router.get("/simulation-results", response_model=list[SimulationResultOut])
async def list_simulation_results(
    job_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[SimulationResult]:
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)

    stmt = select(SimulationResult).order_by(SimulationResult.created_at.desc()).limit(limit).offset(offset)
    if job_id is not None:
        stmt = stmt.where(SimulationResult.job_id == job_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/simulation-results/{result_id}", response_model=SimulationResultOut)
async def get_simulation_result(result_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> SimulationResult:
    result_row = await db.get(SimulationResult, result_id)
    if result_row is None:
        raise not_found("simulation result")
    return result_row


@router.get("/simulation-results/by-job/{job_id}", response_model=SimulationResultOut)
async def get_simulation_result_by_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> SimulationResult:
    result = await db.execute(select(SimulationResult).where(SimulationResult.job_id == job_id))
    result_row = result.scalar_one_or_none()
    if result_row is None:
        raise not_found("simulation result")
    return result_row


@router.patch("/simulation-results/{result_id}", response_model=SimulationResultOut)
async def patch_simulation_result(
    result_id: uuid.UUID, payload: SimulationResultPatch, db: AsyncSession = Depends(get_db)
) -> SimulationResult:
    result_row = await db.get(SimulationResult, result_id)
    if result_row is None:
        raise not_found("simulation result")

    apply_patch(result_row, payload)
    await db.commit()
    await db.refresh(result_row)
    return result_row


@router.delete("/simulation-results/{result_id}")
async def delete_simulation_result(result_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    result_row = await db.get(SimulationResult, result_id)
    if result_row is None:
        raise not_found("simulation result")

    await db.delete(result_row)
    await db.commit()
    return {"deleted": True}
