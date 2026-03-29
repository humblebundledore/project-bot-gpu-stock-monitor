"""Structured logging setup."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(config) -> None:
    """Configure structured logging based on AppConfig."""
    level = getattr(logging, config.log_level.upper(), logging.INFO)

    handlers: list[logging.Handler] = []

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    if config.log_format == "json":
        console.setFormatter(_JsonFormatter())
    else:
        console.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        ))
    handlers.append(console)

    # File handler
    if config.log_file:
        log_path = Path(config.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            config.log_file,
            maxBytes=config.log_rotate_bytes,
            backupCount=config.log_backup_count,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(_JsonFormatter())
        handlers.append(fh)

    logging.basicConfig(level=level, handlers=handlers, force=True)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "playwright", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class _JsonFormatter(logging.Formatter):
    """Simple JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime

        data = {
            "ts": datetime.utcfromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)
