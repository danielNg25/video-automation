import os
import re
from pathlib import Path

import yaml


def _interpolate_env_vars(value: str) -> str:
    """Replace ${VAR} or ${VAR:-default} patterns with environment variable values."""

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2) or ""
        env_value = os.environ.get(var_name)
        if env_value is None or env_value == "":
            return default
        return env_value

    return re.sub(r"\$\{(\w+)(?::-([^}]*))?\}", replacer, value)


def _walk_and_interpolate(obj):
    """Recursively walk a parsed YAML structure and interpolate env vars in strings."""
    if isinstance(obj, str):
        return _interpolate_env_vars(obj)
    elif isinstance(obj, dict):
        return {k: _walk_and_interpolate(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_walk_and_interpolate(item) for item in obj]
    return obj


def save_config(data: dict, path: str = "config/config.yaml") -> None:
    """Save config dict to YAML file (without env var interpolation)."""
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_raw_config(path: str = "config/config.yaml") -> dict:
    """Load YAML config without env var interpolation (for editing)."""
    config_path = Path(path)
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    return raw or {}


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
