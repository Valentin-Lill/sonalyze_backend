from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEASUREMENT_", case_sensitive=False)

    data_dir: str = "/data"
    debug_dir: str = "debug_audio"
    max_upload_mb: int = 50
    
    # Gateway configuration for broadcasting events
    gateway_url: str = os.getenv("GATEWAY_URL", "http://gateway:8000").rstrip("/")
    internal_auth_token: str = os.getenv("INTERNAL_AUTH_TOKEN", "")


settings = Settings()
