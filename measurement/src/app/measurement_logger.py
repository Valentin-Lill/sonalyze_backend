"""
Measurement Service File Logger.

Provides file-based logging specifically for the measurement service
to enable debugging of measurement coordination issues.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

# Default log directory
DEFAULT_LOG_DIR = Path("/var/log/sonalyze")
FALLBACK_LOG_DIR = Path("./logs")

# Log file name
LOG_FILENAME = "measurement_service.log"

# Log format with detailed timestamp and context
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class MeasurementLogger:
    """
    Specialized logger for measurement service operations.

    Features:
    - File-based logging with rotation
    - Structured log entries with context
    - Separate log file for measurement operations only
    - Easy to copy/send for debugging
    """

    _instance: Optional["MeasurementLogger"] = None
    _initialized: bool = False

    def __new__(cls) -> "MeasurementLogger":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if MeasurementLogger._initialized:
            return

        self._logger = logging.getLogger("measurement_service")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False  # Don't propagate to root logger

        # Clear any existing handlers
        self._logger.handlers.clear()

        # Setup file handler
        self._setup_file_handler()

        # Setup console handler (for Docker logs)
        self._setup_console_handler()

        MeasurementLogger._initialized = True
        self.info("MeasurementLogger initialized")

    def _setup_file_handler(self) -> None:
        """Setup rotating file handler."""
        log_dir = self._get_log_directory()
        log_file = log_dir / LOG_FILENAME

        try:
            # Create rotating file handler (10MB max, keep 5 backups)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
            )
            self._logger.addHandler(file_handler)
            self._log_file_path = log_file
        except Exception as e:
            print(f"Failed to setup file handler: {e}", file=sys.stderr)
            self._log_file_path = None

    def _setup_console_handler(self) -> None:
        """Setup console handler for Docker/stdout logging."""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(
            logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        )
        self._logger.addHandler(console_handler)

    def _get_log_directory(self) -> Path:
        """Get or create the log directory."""
        # Try environment variable first
        env_log_dir = os.getenv("MEASUREMENT_LOG_DIR")
        if env_log_dir:
            log_dir = Path(env_log_dir)
        else:
            # Try default directory, fallback to local
            log_dir = DEFAULT_LOG_DIR
            if not log_dir.exists():
                try:
                    log_dir.mkdir(parents=True, exist_ok=True)
                except PermissionError:
                    log_dir = FALLBACK_LOG_DIR

        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    @property
    def log_file_path(self) -> Optional[Path]:
        """Get the current log file path."""
        return self._log_file_path

    def _format_data(self, data: Optional[dict[str, Any]]) -> str:
        """Format data dictionary for logging."""
        if not data:
            return ""
        # Format as key=value pairs for easy parsing
        pairs = [f"{k}={v}" for k, v in data.items()]
        return " | " + " | ".join(pairs)

    def debug(
        self,
        message: str,
        *,
        component: str = "general",
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log a debug message."""
        context = self._build_context(component, session_id, device_id)
        self._logger.debug(f"{context}{message}{self._format_data(data)}")

    def info(
        self,
        message: str,
        *,
        component: str = "general",
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log an info message."""
        context = self._build_context(component, session_id, device_id)
        self._logger.info(f"{context}{message}{self._format_data(data)}")

    def warning(
        self,
        message: str,
        *,
        component: str = "general",
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log a warning message."""
        context = self._build_context(component, session_id, device_id)
        self._logger.warning(f"{context}{message}{self._format_data(data)}")

    def error(
        self,
        message: str,
        *,
        component: str = "general",
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
        exc_info: bool = False,
    ) -> None:
        """Log an error message."""
        context = self._build_context(component, session_id, device_id)
        self._logger.error(
            f"{context}{message}{self._format_data(data)}",
            exc_info=exc_info,
        )

    def _build_context(
        self,
        component: str,
        session_id: Optional[str],
        device_id: Optional[str],
    ) -> str:
        """Build context prefix for log message."""
        parts = [f"[{component}]"]
        if session_id:
            parts.append(f"[session:{session_id[:8]}]")
        if device_id:
            parts.append(f"[device:{device_id[:8]}]")
        return " ".join(parts) + " "

    def log_step(
        self,
        step_number: int,
        step_name: str,
        message: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log a measurement protocol step."""
        if message:
            log_message = f"STEP {step_number}: {step_name} - {message}"
        else:
            log_message = f"STEP {step_number}: {step_name}"
        self.info(
            log_message,
            component="protocol",
            session_id=session_id,
            device_id=device_id,
            data=data,
        )

    def log_event_received(
        self,
        event: str,
        *,
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log an incoming event."""
        self.debug(
            f"Event received: {event}",
            component="gateway",
            session_id=session_id,
            device_id=device_id,
            data=data,
        )

    def log_broadcast(
        self,
        event: str,
        target_devices: list[str],
        *,
        session_id: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log an outgoing broadcast."""
        self.debug(
            f"Broadcasting: {event} to {len(target_devices)} devices",
            component="broadcast",
            session_id=session_id,
            data={"targets": target_devices[:3], **(data or {})},  # Limit device list
        )


# Global logger instance
measurement_log = MeasurementLogger()

# Alias for convenient import
log = measurement_log


def get_measurement_logger() -> MeasurementLogger:
    """Get the measurement logger instance."""
    return measurement_log
