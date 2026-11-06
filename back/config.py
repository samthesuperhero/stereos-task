from __future__ import annotations

import configparser
import math
import os
from dataclasses import dataclass
from pathlib import Path

EX_CONFIG = 78
MAX_SHUTDOWN_TIMEOUT_SECONDS = 20.0
DEFAULT_CONFIG_PATH = Path("/etc/stereos-task/stereos-task.ini")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 61070
    static_dir: Path = Path(__file__).resolve().parent.parent / "front"
    max_request_bytes: int = 8 * 1024 * 1024
    request_timeout_seconds: float = 30.0
    shutdown_timeout_seconds: float = MAX_SHUTDOWN_TIMEOUT_SECONDS
    log_level: str = "INFO"


_ENVIRONMENT = {
    "host": "STEREOS_TASK_HOST",
    "port": "STEREOS_TASK_PORT",
    "static_dir": "STEREOS_TASK_STATIC_DIR",
    "max_request_bytes": "STEREOS_TASK_MAX_REQUEST_BYTES",
    "request_timeout_seconds": "STEREOS_TASK_REQUEST_TIMEOUT_SECONDS",
    "shutdown_timeout_seconds": "STEREOS_TASK_SHUTDOWN_TIMEOUT_SECONDS",
    "log_level": "STEREOS_TASK_LOG_LEVEL",
}


def load_settings(path: Path | None = None) -> Settings:
    selected = path or DEFAULT_CONFIG_PATH
    values: dict[str, str] = {}
    if selected.exists():
        parser = configparser.ConfigParser(interpolation=None)
        try:
            with selected.open(encoding="utf-8") as stream:
                parser.read_file(stream)
        except (OSError, UnicodeError, configparser.Error) as exc:
            raise ConfigError(f"Cannot parse configuration {selected}: {exc}") from exc
        if parser.defaults() or parser.sections() != ["service"]:
            raise ConfigError("Configuration must contain only a [service] section")
        values.update(parser["service"])
    elif path is not None:
        raise ConfigError(f"Configuration file does not exist: {selected}")

    for key, variable in _ENVIRONMENT.items():
        if variable in os.environ:
            values[key] = os.environ[variable]

    try:
        settings = Settings(
            host=values.get("host", Settings.host),
            port=int(values.get("port", Settings.port)),
            static_dir=Path(values.get("static_dir", str(Settings.static_dir))),
            max_request_bytes=int(
                values.get("max_request_bytes", Settings.max_request_bytes)
            ),
            request_timeout_seconds=float(
                values.get(
                    "request_timeout_seconds", Settings.request_timeout_seconds
                )
            ),
            shutdown_timeout_seconds=float(
                values.get(
                    "shutdown_timeout_seconds", Settings.shutdown_timeout_seconds
                )
            ),
            log_level=values.get("log_level", Settings.log_level).upper(),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid configuration value: {exc}") from exc

    if not settings.host.strip():
        raise ConfigError("host must not be empty")
    if not 1 <= settings.port <= 65535:
        raise ConfigError("port must be between 1 and 65535")
    if settings.max_request_bytes < 1024:
        raise ConfigError("max_request_bytes must be at least 1024")
    if not math.isfinite(settings.request_timeout_seconds) or settings.request_timeout_seconds <= 0:
        raise ConfigError("request_timeout_seconds must be finite and positive")
    if (
        not math.isfinite(settings.shutdown_timeout_seconds)
        or not 0 < settings.shutdown_timeout_seconds <= MAX_SHUTDOWN_TIMEOUT_SECONDS
    ):
        raise ConfigError(
            "shutdown_timeout_seconds must be finite and between 0 and "
            f"{MAX_SHUTDOWN_TIMEOUT_SECONDS:g} seconds"
        )
    return settings
