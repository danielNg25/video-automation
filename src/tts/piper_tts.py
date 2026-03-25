"""Piper TTS provider — fast local neural text-to-speech."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Default model directory
DEFAULT_MODEL_DIR = Path("data/tts/piper_models")

# Curated models — user downloads the ones they need
# Format: {voice_name: {url, language, gender, description}}
PIPER_MODELS = {
    "vi_VN-vais1000-medium": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx.json",
        "language": "vi",
        "gender": "female",
        "description": "Vietnamese female (medium quality)",
    },
    "en_US-lessac-medium": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
        "language": "en",
        "gender": "male",
        "description": "English US male (medium quality)",
    },
    "en_US-amy-medium": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json",
        "language": "en",
        "gender": "female",
        "description": "English US female (medium quality)",
    },
    "en_GB-alba-medium": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx.json",
        "language": "en",
        "gender": "female",
        "description": "English GB female (medium quality)",
    },
    "zh_CN-huayan-medium": {
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx",
        "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json",
        "language": "zh",
        "gender": "female",
        "description": "Chinese Mandarin female (medium quality)",
    },
}


class PiperTTSProvider(BaseTTSProvider):
    """Local neural TTS using Piper (ONNX-based, fully offline).

    Requires the `piper-tts` CLI tool to be installed:
        pip install piper-tts

    Models are downloaded on first use to data/tts/piper_models/.
    """

    def __init__(self, model_dir: str | Path | None = None):
        self.model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
        self.model_dir.mkdir(parents=True, exist_ok=True)

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        """Synthesize speech using Piper.

        Args:
            text: Text to synthesize.
            voice: Piper model name (e.g., "vi_VN-vais1000-medium").
            **kwargs: Optional 'length_scale' (float, >1 = slower, <1 = faster).

        Returns:
            WAV audio bytes.
        """
        model_path = self.model_dir / f"{voice}.onnx"
        config_path = self.model_dir / f"{voice}.onnx.json"

        # Download model if not present
        if not model_path.exists():
            await self._download_model(voice)

        if not model_path.exists():
            raise FileNotFoundError(
                f"Piper model '{voice}' not found at {model_path}. "
                f"Available models: {list(PIPER_MODELS.keys())}"
            )

        length_scale = kwargs.get("length_scale", 1.0)
        if isinstance(length_scale, str):
            # Convert "+10%" style to float
            length_scale = 1.0 + float(length_scale.replace("%", "").replace("+", "")) / 100

        def _generate() -> bytes:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            cmd = [
                "piper",
                "--model", str(model_path),
                "--output_file", tmp_path,
                "--length-scale", str(length_scale),
            ]
            if config_path.exists():
                cmd.extend(["--config", str(config_path)])

            result = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Piper failed: {result.stderr[:300]}")

            wav_bytes = Path(tmp_path).read_bytes()
            Path(tmp_path).unlink(missing_ok=True)
            return wav_bytes

        return await asyncio.to_thread(_generate)

    async def _download_model(self, voice: str) -> None:
        """Download a Piper model from HuggingFace."""
        model_info = PIPER_MODELS.get(voice)
        if not model_info:
            logger.warning(f"Unknown Piper model: {voice}")
            return

        import httpx

        model_path = self.model_dir / f"{voice}.onnx"
        config_path = self.model_dir / f"{voice}.onnx.json"

        logger.info(f"Downloading Piper model: {voice}...")

        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            # Download model file
            resp = await client.get(model_info["url"])
            resp.raise_for_status()
            model_path.write_bytes(resp.content)
            logger.info(f"Downloaded model: {model_path} ({len(resp.content) / 1024 / 1024:.1f} MB)")

            # Download config file
            resp = await client.get(model_info["config_url"])
            resp.raise_for_status()
            config_path.write_bytes(resp.content)

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """List available Piper voices.

        Shows all curated models with download status.
        """
        results = []
        for name, info in PIPER_MODELS.items():
            if language and info["language"] != language:
                continue

            model_path = self.model_dir / f"{name}.onnx"
            downloaded = model_path.exists()

            results.append({
                "name": name,
                "language": info["language"],
                "gender": info["gender"],
                "provider": "piper",
                "friendly_name": f"{info['description']}{' [downloaded]' if downloaded else ' [will download]'}",
            })
        return results
