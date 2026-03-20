"""Shared dependencies for API routes."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from src.utils.config import load_config

if TYPE_CHECKING:
    from src.api.task_manager import TaskManager

_task_manager: TaskManager | None = None


@lru_cache
def get_config() -> dict:
    """Load and cache config. Falls back to example config if config.yaml missing."""
    config_path = "config/config.yaml"
    if not os.path.exists(config_path):
        config_path = "config/config.example.yaml"
    return load_config(config_path)


def get_data_dir() -> Path:
    """Return the data directory, creating subdirs if needed."""
    data = Path("data")
    for sub in ("raw", "srt", "output", "logs"):
        (data / sub).mkdir(parents=True, exist_ok=True)
    return data


def get_task_manager() -> TaskManager:
    """Return the singleton TaskManager instance."""
    global _task_manager
    if _task_manager is None:
        from src.api.task_manager import TaskManager

        _task_manager = TaskManager()
    return _task_manager
