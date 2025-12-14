from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.routers import (
    analysis_outputs,
    devices,
    lobbies,
    measurements,
    participants,
    simulation_jobs,
    simulation_results,
)

app = FastAPI(title="sonalyze-storage", version="0.1.0", default_response_class=ORJSONResponse)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


app.include_router(devices.router, prefix="/v1")
app.include_router(lobbies.router, prefix="/v1")
app.include_router(participants.router, prefix="/v1")
app.include_router(measurements.router, prefix="/v1")
app.include_router(analysis_outputs.router, prefix="/v1")
app.include_router(simulation_jobs.router, prefix="/v1")
app.include_router(simulation_results.router, prefix="/v1")
