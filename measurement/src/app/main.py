from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(title="sonalyze-measurement", version="0.1.0")
app.include_router(router)


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
