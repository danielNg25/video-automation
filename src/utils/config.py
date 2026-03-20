import os
import re
from pathlib import Path

import yaml


def _interpolate_env_vars(value: str) -> str:
    """Replace ${VAR} patterns with environment variable values."""

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        return env_value

    return re.sub(r"\$\{(\w+)\}", replacer, value)


def _walk_and_interpolate(obj):
    """Recursively walk a parsed YAML structure and interpolate env vars in strings."""
    if isinstance(obj, str):
        return _interpolate_env_vars(obj)
    elif isinstance(obj, dict):
        return {k: _walk_and_interpolate(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_walk_and_interpolate(item) for item in obj]
    return obj


def load_config(path: str = "config/config.yaml") -> dict:
    """Load YAML config with ${ENV_VAR} interpolation.

    Args:
        path: Path to YAML config file.

    Returns:
        Parsed config dict with env vars resolved.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if raw is None:
        return {}

    return _walk_and_interpolate(raw)
