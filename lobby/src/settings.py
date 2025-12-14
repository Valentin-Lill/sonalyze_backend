from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "lobby"
    database_url: str = "sqlite+aiosqlite:///./lobby.db"


settings = Settings()
