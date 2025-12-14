from __future__ import annotations

from fastapi import FastAPI

from sonalyze_simulation.routes import router

app = FastAPI(title="sonalyze-simulation", version="0.1.0")
app.include_router(router)
