"""LLM-based subtitle translator with profile-guided style control.

Translates SRT files segment-by-segment via Anthropic or OpenAI APIs,
using TranslationProfile to control tone, style, and personality.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from pathlib import Path

from src.processor.subtitle import parse_srt, write_srt
from src.translator.profiles import TranslationProfile
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class LLMTranslator:
    def __init__(
        self,
        backend: str = "anthropic",
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        base_url: str | None = None,
        max_segments_per_batch: int = 8,
        temperature: float = 0.7,
    ):
        self.backend = backend
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_segments_per_batch = max_segments_per_batch
        self.temperature = temperature
        self._client = None

    def _build_system_prompt(self, profile: TranslationProfile) -> str:
        parts = [
            f"You are a subtitle translator from {profile.source_language} to "
            f"{profile.target_language}.",
            "",
            profile.style_guide,
        ]

        if profile.example_pairs:
            parts.append("")
            parts.append("Here are example translations to follow:")
            for pair in profile.example_pairs:
                parts.append(f"  {profile.source_language}: {pair['source']}")
                parts.append(f"  {profile.target_language}: {pair['target']}")
                parts.append("")

        return "\n".join(parts)

    def _build_batch_prompt(
        self,
        segments: list[dict],
        profile: TranslationProfile,
        context_segments: list[dict] | None = None,
    ) -> str:
        parts = []

        if context_segments:
            parts.append("Previous subtitles for context (do NOT translate these):")
            for seg in context_segments:
                parts.append(f"  > {seg['text']}")
            parts.append("")

        parts.append(
            f"Translate the following {len(segments)} subtitle segments from "
            f"{profile.source_language} to {profile.target_language}."
        )
        parts.append(
            "Return ONLY the translations, one per line, matching the input order exactly."
        )
        parts.append(f"You must return exactly {len(segments)} lines.")
        parts.append("")

        for i, seg in enumerate(segments, 1):
            text = seg["text"].replace("\n", " ")
            parts.append(f"{i}. {text}")

        return "\n".join(parts)

    async def _call_anthropic(self, system: str, user: str) -> str:
        import anthropic

        if self._client is None:
            kwargs = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            self._client = anthropic.AsyncAnthropic(**kwargs)

        response = await self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    async def _call_openai(self, system: str, user: str) -> str:
        import openai

        if self._client is None:
            kwargs = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.AsyncOpenAI(**kwargs)

        response = await self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content

    async def _call_local(self, system: str, user: str) -> str:
        """Run inference on a local model via mlx-lm (macOS) or llama-cpp-python (Linux)."""
        import sys

        if sys.platform == "darwin":
            return await self._call_mlx(system, user)
        else:
            return await self._call_llama_cpp(system, user)

    async def _call_mlx(self, system: str, user: str) -> str:
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler

        # Lazy-load model on first call
        if self._client is None:
            logger.info(f"Loading local model: {self.model} (this may take a moment)...")
            model, tokenizer = load(self.model)
            self._client = (model, tokenizer)

        model, tokenizer = self._client

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        sampler = make_sampler(temp=self.temperature)

        # Run CPU/GPU-bound generation in a thread
        response = await asyncio.to_thread(
            generate,
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=4096,
            sampler=sampler,
            verbose=False,
        )
        return response

    async def _call_llama_cpp(self, system: str, user: str) -> str:
        from llama_cpp import Llama

        # Lazy-load model on first call
        if self._client is None:
            logger.info(f"Loading local model: {self.model} (this may take a moment)...")

            # Model can be a HuggingFace repo with GGUF files
            # Format: "repo_id/filename.gguf" or just "repo_id" (auto-picks best file)
            if "/" in self.model and ".gguf" in self.model:
                # Explicit file: "Qwen/Qwen2.5-14B-Instruct-GGUF/qwen2.5-14b-instruct-q4_k_m.gguf"
                parts = self.model.rsplit("/", 1)
                repo_id, filename = parts[0], parts[1]
            else:
                # Repo ID only — use from_pretrained with auto-select
                repo_id = self.model
                filename = "*q4_k_m.gguf"  # prefer Q4_K_M quantization

            self._client = Llama.from_pretrained(
                repo_id=repo_id,
                filename=filename,
                n_ctx=4096,
                n_gpu_layers=-1,  # offload all layers to GPU
                verbose=False,
            )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        # Run CPU/GPU-bound generation in a thread
        response = await asyncio.to_thread(
            self._client.create_chat_completion,
            messages=messages,
            max_tokens=4096,
            temperature=self.temperature,
        )
        return response["choices"][0]["message"]["content"]

    async def _call_llm(self, system: str, user: str) -> str:
        if self.backend == "anthropic":
            return await self._call_anthropic(system, user)
        elif self.backend == "openai":
            return await self._call_openai(system, user)
        elif self.backend == "local":
            return await self._call_local(system, user)
        else:
            raise ValueError(f"Unsupported backend: {self.backend}")

    def _parse_response(self, response: str, expected_count: int) -> list[str]:
        """Parse LLM response into individual translations."""
        lines = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Strip leading number prefix like "1. " or "1) "
            line = re.sub(r"^\d+[\.\)]\s*", "", line)
            lines.append(line)
        return lines

    async def translate_srt(
        self,
        srt_path: Path,
        profile: TranslationProfile,
        output_path: Path,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> Path:
        """Translate an SRT file using the LLM with the given profile.

        Args:
            srt_path: Path to source SRT file.
            profile: Translation profile controlling style/tone.
            output_path: Path for translated SRT output.
            progress_callback: Called with (batch_num, total_batches, message).

        Returns:
            Path to translated SRT file.
        """
        segments = parse_srt(srt_path)
        if not segments:
            logger.warning(f"No segments found in {srt_path}")
            write_srt([], output_path)
            return output_path

        # Filter out empty segments, keep indices for reassembly
        non_empty = [(i, seg) for i, seg in enumerate(segments) if seg["text"].strip()]
        empty_indices = {i for i in range(len(segments)) if not segments[i]["text"].strip()}

        # Batch non-empty segments
        batches = []
        for i in range(0, len(non_empty), self.max_segments_per_batch):
            batches.append(non_empty[i : i + self.max_segments_per_batch])

        total_batches = len(batches)
        system_prompt = self._build_system_prompt(profile)
        translations: dict[int, str] = {}  # original_index -> translated_text

        logger.info(
            f"Translating {len(non_empty)} segments in {total_batches} batches "
            f"({profile.name}, {self.backend}/{self.model})"
        )

        for batch_num, batch in enumerate(batches, 1):
            batch_segments = [seg for _, seg in batch]
            batch_indices = [idx for idx, _ in batch]

            # Include previous 2 segments as context
            context = None
            if batch_num > 1:
                prev_batch = batches[batch_num - 2]
                context = [seg for _, seg in prev_batch[-2:]]

            user_prompt = self._build_batch_prompt(batch_segments, profile, context)
            msg = f"Translating batch {batch_num}/{total_batches}..."

            if progress_callback:
                progress_callback(batch_num, total_batches, msg)
            logger.info(msg)

            response = await self._call_llm(system_prompt, user_prompt)
            parsed = self._parse_response(response, len(batch_segments))

            if len(parsed) != len(batch_segments):
                logger.warning(
                    f"Batch {batch_num}: expected {len(batch_segments)} translations, "
                    f"got {len(parsed)}. Retrying..."
                )
                # Retry with stricter instruction
                retry_prompt = (
                    user_prompt
                    + f"\n\nIMPORTANT: You MUST return exactly {len(batch_segments)} lines, "
                    "no more, no less. One translation per line."
                )
                response = await self._call_llm(system_prompt, retry_prompt)
                parsed = self._parse_response(response, len(batch_segments))

            # Map translations to original indices
            for j, orig_idx in enumerate(batch_indices):
                if j < len(parsed):
                    translations[orig_idx] = parsed[j]
                else:
                    # Fallback: use original text
                    translations[orig_idx] = batch_segments[j]["text"]
                    logger.warning(
                        f"Missing translation for segment {orig_idx + 1}, using original"
                    )

            # Rate limiting between batches (skip for local models)
            if batch_num < total_batches and self.backend != "local":
                await asyncio.sleep(1)

        # Reassemble all segments with translations
        translated_segments = []
        for i, seg in enumerate(segments):
            translated_segments.append(
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": translations.get(i, seg["text"]) if i not in empty_indices else "",
                }
            )

        write_srt(translated_segments, output_path)

        logger.info(
            f"Translation complete: {output_path} "
            f"({len(translated_segments)} segments, profile={profile.name})"
        )

        return output_path
