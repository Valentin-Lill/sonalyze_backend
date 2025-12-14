from __future__ import annotations

from fastapi import FastAPI

from sonalyze_simulation.routes import router
from sonalyze_simulation.gateway_handler import router as gateway_router

app = FastAPI(title="sonalyze-simulation", version="0.1.0")
app.include_router(router)

# Include gateway handler for WebSocket event forwarding
app.include_router(gateway_router)
