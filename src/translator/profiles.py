"""Translation profile system for LLM-based subtitle translation.

Profiles control the style, tone, and personality of translations.
Stored as YAML files in config/translation_profiles/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_DEFAULT_PROFILES_DIR = Path("config/translation_profiles")


@dataclass
class TranslationProfile:
    name: str
    description: str
    style_guide: str
    target_language: str
    source_language: str = "zh"
    example_pairs: list[dict] = field(default_factory=list)


def _profiles_dir(profiles_dir: Path | None = None) -> Path:
    return profiles_dir or _DEFAULT_PROFILES_DIR


def load_profile(name: str, profiles_dir: Path | None = None) -> TranslationProfile:
    """Load a translation profile from YAML."""
    d = _profiles_dir(profiles_dir)
    path = d / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Translation profile not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    return TranslationProfile(
        name=data["name"],
        description=data.get("description", ""),
        style_guide=data.get("style_guide", ""),
        target_language=data.get("target_language", "vi"),
        source_language=data.get("source_language", "zh"),
        example_pairs=data.get("example_pairs", []),
    )


def list_profiles(profiles_dir: Path | None = None) -> list[str]:
    """List available profile names (excludes .example files)."""
    d = _profiles_dir(profiles_dir)
    if not d.exists():
        return []
    return sorted(
        f.stem
        for f in d.glob("*.yaml")
        if not f.name.endswith(".example")
    )


def save_profile(profile: TranslationProfile, profiles_dir: Path | None = None) -> None:
    """Save a translation profile to YAML."""
    d = _profiles_dir(profiles_dir)
    d.mkdir(parents=True, exist_ok=True)

    data = {
        "name": profile.name,
        "description": profile.description,
        "target_language": profile.target_language,
        "source_language": profile.source_language,
        "style_guide": profile.style_guide,
        "example_pairs": profile.example_pairs,
    }

    path = d / f"{profile.name}.yaml"
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    logger.info(f"Saved translation profile: {path}")


def delete_profile(name: str, profiles_dir: Path | None = None) -> None:
    """Delete a translation profile."""
    d = _profiles_dir(profiles_dir)
    path = d / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Translation profile not found: {path}")
    path.unlink()
    logger.info(f"Deleted translation profile: {name}")


def get_default_profile(target_lang: str, profiles_dir: Path | None = None) -> str | None:
    """Return the first profile matching the target language, or None."""
    d = _profiles_dir(profiles_dir)
    for name in list_profiles(d):
        try:
            p = load_profile(name, d)
            if p.target_language == target_lang:
                return name
        except Exception:
            continue
    return None
