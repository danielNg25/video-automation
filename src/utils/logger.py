import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "video_id"):
            log_entry["video_id"] = record.video_id
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

    # File handler with JSON formatting
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "pipeline.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    return logger
