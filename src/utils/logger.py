"""Structured JSON logging with rich console output and per-video log files."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

LOG_DIR = Path("data/logs")


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON lines with structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Structured context fields
        for field in ("video_id", "stage", "duration_ms", "extra"):
            if hasattr(record, field):
                log_entry[field] = getattr(record, field)

        return json.dumps(log_entry)


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Set up a logger with rich console output and JSON file output.

    Args:
        name: Logger name (typically module name).
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if logger.handlers:
        return logger

    # Console handler with rich formatting
    console = Console(stderr=True)
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
    )
    console_handler.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)

    # File handler with JSON formatting → data/logs/pipeline.log
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_DIR / "pipeline.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    return logger


def get_video_logger(video_id: str) -> logging.Logger:
    """Get a per-video logger that writes to data/logs/{video_id}.log.

    This logger also writes to the main pipeline.log and console. It
    automatically attaches video_id to every record.

    Args:
        video_id: The video identifier.

    Returns:
        Logger with video_id context and per-video file handler.
    """
    logger_name = f"pipeline.{video_id}"
    logger = logging.getLogger(logger_name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Per-video JSON log file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    video_handler = logging.FileHandler(LOG_DIR / f"{video_id}.log")
    video_handler.setLevel(logging.DEBUG)
    video_handler.setFormatter(JSONFormatter())
    logger.addHandler(video_handler)

    # Add filter to inject video_id into every record
    class VideoIdFilter(logging.Filter):
        def filter(self, record):
            record.video_id = video_id
            return True

    logger.addFilter(VideoIdFilter())

    # Propagate to root loggers for console + pipeline.log
    logger.propagate = True

    return logger
