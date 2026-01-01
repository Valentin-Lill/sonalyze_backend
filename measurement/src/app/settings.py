from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEASUREMENT_", case_sensitive=False)

    data_dir: str = "/data"
    debug_dir: str = "debug_audio"
    max_upload_mb: int = 50


settings = Settings()
