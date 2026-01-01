from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "lobby"
    database_url: str = "sqlite+aiosqlite:///./lobby.db"
    gateway_url: str = "http://localhost:8000"
    measurement_url: str = "http://measurement:8000"
    internal_auth_token: str = ""


settings = Settings()
