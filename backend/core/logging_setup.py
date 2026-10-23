from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from backend.config import settings


LOGGER_NAME = "diskshell"
_HANDLER_MARKER = "_diskshell_handler"


def _format_fields(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value).replace("\n", "\\n").replace("\r", "\\r")
        parts.append(f"{key}={text!r}")
    return " ".join(parts)


def configure_logging(log_dir: Path | None = None) -> logging.Logger:
    target_dir = Path(log_dir) if log_dir is not None else settings.data_dir / "logs"
    target_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        target_dir / "diskshell.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    setattr(file_handler, _HANDLER_MARKER, True)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    setattr(console_handler, _HANDLER_MARKER, True)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # The browser is a control surface. Routine HTTP traffic is implementation
    # detail, not an operator event. Flask/Werkzeug's request logger is therefore
    # silenced; meaningful failures are captured through the DiskShell journal.
    werkzeug = logging.getLogger("werkzeug")
    werkzeug.disabled = True
    werkzeug.propagate = False

    # Waitress normally stays quiet for requests, but keep its own diagnostics
    # at warning/error level when production mode is used.
    waitress = logging.getLogger("waitress")
    waitress.setLevel(logging.WARNING)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def log_event(event: str, **fields: Any) -> None:
    suffix = _format_fields(fields)
    get_logger().info("%s%s", event, f" {suffix}" if suffix else "")


def log_warning(event: str, **fields: Any) -> None:
    suffix = _format_fields(fields)
    get_logger().warning("%s%s", event, f" {suffix}" if suffix else "")


def log_error(event: str, **fields: Any) -> None:
    suffix = _format_fields(fields)
    get_logger().error("%s%s", event, f" {suffix}" if suffix else "")
