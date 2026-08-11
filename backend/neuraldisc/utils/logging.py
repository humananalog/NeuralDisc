"""Structured logging setup."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog


def setup_logging(log_dir: Path | None = None, level: str = "INFO") -> None:
    """Configure structlog + stdlib logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        foreign_pre_chain=shared_processors,
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(log_level)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(console_formatter)
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "neuraldisc.log")
        file_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        file_handler.setFormatter(file_formatter)
        root.addHandler(file_handler)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
