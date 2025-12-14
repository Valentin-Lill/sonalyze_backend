from __future__ import annotations

import os


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


class Settings:
    def __init__(self) -> None:
        self.lobby_url = os.getenv("LOBBY_URL", "http://lobby:8000").rstrip("/")
        self.measurement_url = os.getenv("MEASUREMENT_URL", "http://measurement:8000").rstrip("/")
        self.simulation_url = os.getenv("SIMULATION_URL", "http://simulation:8000").rstrip("/")

        self.internal_auth_token = os.getenv("INTERNAL_AUTH_TOKEN", "")

        self.max_message_bytes = _get_int("MAX_MESSAGE_BYTES", 65536)
        self.rate_limit_rps = _get_float("RATE_LIMIT_RPS", 10.0)
        self.rate_limit_burst = _get_int("RATE_LIMIT_BURST", 20)

        self.http_timeout_seconds = _get_float("HTTP_TIMEOUT_SECONDS", 10.0)


settings = Settings()
