from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEASUREMENT_", case_sensitive=False)

    data_dir: str = "/data"
    max_upload_mb: int = 50


settings = Settings()
