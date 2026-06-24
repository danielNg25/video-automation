"""Vbee (vbee.vn / AIVoice) TTS provider — async submit→poll→download.

Vbee's synthesis API is asynchronous: POST returns a requestId, you poll
GET /tts/requests/{id} until COMPLETED with an audioLink, then download
that URL. The whole flow is hidden inside synthesize() so the rest of the
pipeline keeps its synchronous "synthesize(text, voice) -> bytes" contract.
"""

from __future__ import annotations

import asyncio

import httpx

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def _vbee_error(resp: httpx.Response) -> str:
    """Build a readable error string from a vbee error response."""
    try:
        data = resp.json()
        err = data.get("error") or {}
        code = err.get("code") or resp.status_code
        message = err.get("message") or resp.text
        return f"vbee API error {code}: {message}"
    except Exception:
        return f"vbee API error {resp.status_code}: {resp.text}"


class VbeeTTSProvider(BaseTTSProvider):
    """TTS provider for Vbee's Vietnamese voices (async Batch API)."""

    BASE_URL = "https://api.vbee.vn/v1"
    DEFAULT_VOICE = "hn_female_ngochuyen_full_48k-fhg"

    # Curated Vietnamese voices (code, friendly label). Extend by editing.
    VOICES: tuple[tuple[str, str], ...] = (
        ("hn_female_ngochuyen_full_48k-fhg", "Ngọc Huyền — Hà Nội, nữ"),
        ("hn_male_manhdung_news_48k-fhg", "Mạnh Dũng — Hà Nội, nam"),
        ("sg_female_thaotrinh_full_48k-fhg", "Thảo Trinh — Sài Gòn, nữ"),
        ("sg_male_minhhoang_full_48k-fhg", "Minh Hoàng — Sài Gòn, nam"),
        ("hue_female_huonggiang_full_48k-fhg", "Hương Giang — Huế, nữ"),
    )

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.api_key: str = config.get("vbee_api_key", "")
        self.app_id: str = config.get("vbee_app_id", "")
        self.default_voice: str = config.get("vbee_default_voice", self.DEFAULT_VOICE)
        self.output_format: str = config.get("vbee_output_format", "mp3")
        self.bitrate: int = int(config.get("vbee_bitrate", 128))
        self.sample_rate = config.get("vbee_sample_rate")  # None => voice default
        # webhookUrl is a required field even though we poll; placeholder is fine.
        self.webhook_url: str = config.get(
            "vbee_webhook_url", "https://example.com/vbee-callback"
        )
        self.poll_interval_s: float = float(config.get("vbee_poll_interval", 2.0))
        self.poll_timeout_s: float = float(config.get("vbee_poll_timeout", 90.0))

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "App-Id": self.app_id,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _coerce_speed(raw) -> float:
        """Normalise a speed kwarg to vbee's 0.25–1.9 numeric range.

        Accepts floats, numeric strings, and OpenAI-style '+10%' strings.
        """
        speed = raw if raw is not None else 1.0
        if isinstance(speed, str):
            s = speed.strip()
            if s.endswith("%"):
                speed = 1.0 + float(s.replace("%", "").replace("+", "")) / 100
            else:
                speed = float(s)
        speed = float(speed)
        return max(0.25, min(1.9, speed))

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        if not self.api_key or not self.app_id:
            raise ValueError("Vbee token/app_id not configured for TTS")

        body = {
            "text": text,
            "voiceCode": voice or self.default_voice,
            "mode": "async",
            "webhookUrl": self.webhook_url,
            "outputFormat": self.output_format,
            "bitrate": self.bitrate,
            "speed": self._coerce_speed(kwargs.get("speed", 1.0)),
        }
        if self.sample_rate:
            body["sampleRate"] = int(self.sample_rate)

        async with httpx.AsyncClient(timeout=60.0) as client:
            request_id = await self._submit(client, body)
            audio_link = await self._poll(client, request_id)
            audio = await client.get(audio_link)
            audio.raise_for_status()
            return audio.content

    async def _submit(self, client: httpx.AsyncClient, body: dict, max_retries: int = 3) -> str:
        last_err = "vbee submit failed"
        for attempt in range(max_retries):
            resp = await client.post(
                f"{self.BASE_URL}/tts", headers=self._headers(), json=body
            )
            if resp.status_code == 429:
                last_err = "vbee rate limited (429)"
                logger.warning(f"{last_err}; retry {attempt + 1}/{max_retries}")
                await asyncio.sleep(self.poll_interval_s * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise RuntimeError(_vbee_error(resp))
            data = resp.json()
            request_id = data.get("requestId")
            if not request_id:
                raise RuntimeError(f"vbee submit returned no requestId: {data}")
            return request_id
        raise RuntimeError(last_err)

    async def _poll(self, client: httpx.AsyncClient, request_id: str) -> str:
        url = f"{self.BASE_URL}/tts/requests/{request_id}"
        elapsed = 0.0
        while elapsed < self.poll_timeout_s:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code >= 400:
                raise RuntimeError(_vbee_error(resp))
            data = resp.json()
            status = (data.get("status") or "").upper()
            if status in ("COMPLETED", "SUCCESS"):
                audio_link = data.get("audioLink") or data.get("audio_link")
                if not audio_link:
                    raise RuntimeError(f"vbee COMPLETED but no audioLink: {data}")
                return audio_link
            if status in ("FAILED", "FAILURE"):
                raise RuntimeError(f"vbee synthesis failed: {data}")
            await asyncio.sleep(self.poll_interval_s)
            elapsed += self.poll_interval_s
        raise RuntimeError(
            f"vbee synthesis timed out after {self.poll_timeout_s}s (request {request_id})"
        )

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """Curated Vietnamese voice list. `language` is ignored (all vi).

        Custom voice codes are supplied free-text from the UI, so this only
        needs to surface the known-good defaults for the dropdown.
        """
        out = []
        for code, label in self.VOICES:
            gender = "female" if "_female_" in code else "male" if "_male_" in code else "neutral"
            out.append({
                "name": code,
                "language": "vi",
                "gender": gender,
                "provider": "vbee",
                "friendly_name": label,
            })
        return out
