from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.http_errors import not_found
from app.models import AnalysisOutput
from app.schemas import AnalysisOutputCreate, AnalysisOutputOut, AnalysisOutputPatch

from ._common import apply_patch

router = APIRouter(tags=["analysis_outputs"])


@router.post("/analysis-outputs", response_model=AnalysisOutputOut)
async def create_analysis_output(payload: AnalysisOutputCreate, db: AsyncSession = Depends(get_db)) -> AnalysisOutput:
    output = AnalysisOutput(
        measurement_id=payload.measurement_id,
        type=payload.type,
        status=payload.status or "created",
        result=payload.result,
    )
    db.add(output)
    await db.commit()
    await db.refresh(output)
    return output


@router.get("/analysis-outputs", response_model=list[AnalysisOutputOut])
async def list_analysis_outputs(
    measurement_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[AnalysisOutput]:
    limit = min(max(limit, 1), 500)
    offset = max(offset, 0)

    stmt = select(AnalysisOutput).order_by(AnalysisOutput.created_at.desc()).limit(limit).offset(offset)
    if measurement_id is not None:
        stmt = stmt.where(AnalysisOutput.measurement_id == measurement_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/analysis-outputs/{output_id}", response_model=AnalysisOutputOut)
async def get_analysis_output(output_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> AnalysisOutput:
    output = await db.get(AnalysisOutput, output_id)
    if output is None:
        raise not_found("analysis output")
    return output


@router.patch("/analysis-outputs/{output_id}", response_model=AnalysisOutputOut)
async def patch_analysis_output(
    output_id: uuid.UUID, payload: AnalysisOutputPatch, db: AsyncSession = Depends(get_db)
) -> AnalysisOutput:
    output = await db.get(AnalysisOutput, output_id)
    if output is None:
        raise not_found("analysis output")

    apply_patch(output, payload)
    await db.commit()
    await db.refresh(output)
    return output


@router.delete("/analysis-outputs/{output_id}")
async def delete_analysis_output(output_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    output = await db.get(AnalysisOutput, output_id)
    if output is None:
        raise not_found("analysis output")

    await db.delete(output)
    await db.commit()
    return {"deleted": True}
