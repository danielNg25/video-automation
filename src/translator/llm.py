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
        full_document_threshold: int = 100,
        chunk_size: int = 50,
        temperature: float = 0.7,
        skip_noise: bool = True,
    ):
        self.backend = backend
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_segments_per_batch = max_segments_per_batch
        self.full_document_threshold = full_document_threshold
        self.chunk_size = chunk_size
        self.temperature = temperature
        self.skip_noise = skip_noise
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

        if self.skip_noise:
            parts.append("")
            parts.append(
                "Some inputs may be OCR noise — channel handles (e.g. '@user', "
                "'抖音号: xyz'), watermark text, or random fragments that aren't "
                "part of the actual subtitle. For those, output the literal "
                "__SKIP__ (exactly, no quotes, no translation) as the entire "
                "translation for that numbered line. Do NOT attempt to translate "
                "watermarks or handles. Use the surrounding context to judge what "
                "is real subtitle text vs noise."
            )

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

    def _build_full_document_prompt(
        self,
        segments: list[dict],
        profile: TranslationProfile,
    ) -> str:
        """Build a prompt that sends ALL segments at once for full-context translation."""
        parts = [
            f"Translate this complete video subtitle transcript from "
            f"{profile.source_language} to {profile.target_language}.",
            "",
            "RULES:",
            f"- Return exactly {len(segments)} numbered lines matching the input numbering.",
            "- Each translated line corresponds to the same-numbered input line.",
            "- Translate naturally for subtitle display — keep lines concise.",
            "- Maintain narrative coherence across the entire transcript.",
            "- Preserve the emotional tone and pacing of the original.",
            "- If two consecutive short segments form one thought, you may adjust phrasing "
            "but MUST still return them as separate numbered lines.",
            "",
        ]

        for i, seg in enumerate(segments, 1):
            text = seg["text"].replace("\n", " ")
            parts.append(f"{i}. {text}")

        return "\n".join(parts)

    def _build_chunked_document_prompt(
        self,
        all_segments: list[dict],
        chunk_local_indices: list[int],
        profile: TranslationProfile,
        previous_translations: dict[int, str] | None = None,
    ) -> str:
        """Build a prompt with full transcript as context, requesting translation of a chunk only.

        Args:
            all_segments: All non-empty segments (0-indexed).
            chunk_local_indices: Indices within all_segments for this chunk.
            profile: Translation profile.
            previous_translations: Dict of original_segment_index -> translated text
                from previous chunks (for consistency).
        """
        parts = [
            f"Here is the complete subtitle transcript for context "
            f"(DO NOT translate these, they are reference only):",
        ]
        for i, seg in enumerate(all_segments, 1):
            text = seg["text"].replace("\n", " ")
            parts.append(f"{i}. {text}")
        parts.append("")

        if previous_translations:
            parts.append("Previously translated segments (for consistency reference):")
            for idx in sorted(previous_translations.keys()):
                parts.append(f"{idx + 1}. {previous_translations[idx]}")
            parts.append("")

        # Use 1-based numbering matching the full transcript
        chunk_start_display = chunk_local_indices[0] + 1
        chunk_end_display = chunk_local_indices[-1] + 1
        parts.append(
            f"Now translate ONLY segments {chunk_start_display} through {chunk_end_display} from "
            f"{profile.source_language} to {profile.target_language}."
        )
        parts.append(
            f"Return exactly {len(chunk_local_indices)} numbered lines, "
            f"starting from {chunk_start_display}."
        )
        parts.append("")
        for idx in chunk_local_indices:
            text = all_segments[idx]["text"].replace("\n", " ")
            parts.append(f"{idx + 1}. {text}")

        return "\n".join(parts)

    def _parse_numbered_response(
        self,
        response: str,
        prompt_number_to_index: dict[int, int],
    ) -> dict[int, str]:
        """Parse LLM response with robust number-based matching.

        Args:
            response: Raw LLM response text.
            prompt_number_to_index: Maps 1-based prompt numbers to 0-based
                original segment indices. E.g., {1: 0, 2: 3, 3: 5} means
                prompt line "1." maps to original segment 0, "2." to 3, etc.

        Returns:
            Dict mapping 0-based original segment index to translated text.
        """
        result: dict[int, str] = {}
        numbered_lines: list[tuple[int, str]] = []

        for line in response.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Match numbered lines: "1. text", "1) text", "1: text", "1- text"
            m = re.match(r"^(\d+)\s*[\.\):\-]\s*(.+)$", line)
            if m:
                num = int(m.group(1))
                text = m.group(2).strip()
                numbered_lines.append((num, text))

        if numbered_lines:
            for num, text in numbered_lines:
                if num in prompt_number_to_index:
                    result[prompt_number_to_index[num]] = text
        else:
            # Fallback: positional matching (no numbers found)
            lines = [
                ln.strip()
                for ln in response.strip().split("\n")
                if ln.strip()
            ]
            expected_indices = list(prompt_number_to_index.values())
            for i, idx in enumerate(expected_indices):
                if i < len(lines):
                    result[idx] = re.sub(r"^\d+[\.\)]\s*", "", lines[i])

        expected_count = len(prompt_number_to_index)
        if len(result) != expected_count:
            missing = set(prompt_number_to_index.values()) - set(result.keys())
            logger.warning(
                f"Expected {expected_count} translations, got {len(result)}. "
                f"Missing original indices: {missing}"
            )

        return result

    def _find_natural_chunk_boundaries(
        self, segments: list[dict], chunk_size: int
    ) -> list[list[int]]:
        """Split segment indices into chunks, preferring natural pause points (time gaps > 2s)."""
        n = len(segments)
        if n <= chunk_size:
            return [list(range(n))]

        chunks = []
        start = 0
        while start < n:
            if start + chunk_size >= n:
                chunks.append(list(range(start, n)))
                break

            # Look for the largest time gap in a window around the target boundary
            target = start + chunk_size
            window_start = max(start + 1, target - 5)
            window_end = min(n - 1, target + 5)

            best_gap = -1.0
            best_boundary = target
            for i in range(window_start, window_end):
                gap = segments[i]["start"] - segments[i - 1]["end"]
                if gap > best_gap:
                    best_gap = gap
                    best_boundary = i

            chunks.append(list(range(start, best_boundary)))
            start = best_boundary

        return chunks

    def _estimate_max_tokens(self, segment_count: int) -> int:
        """Estimate max output tokens based on segment count."""
        # ~80 tokens per translated segment as upper bound
        estimated = max(4096, segment_count * 80)
        # Cap for local models
        if self.backend == "local":
            return min(estimated, 4096)
        return min(estimated, 16384)

    async def _call_anthropic(self, system: str, user: str, max_tokens: int = 4096) -> str:
        import anthropic

        if self._client is None:
            kwargs = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            self._client = anthropic.AsyncAnthropic(**kwargs)

        response = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    async def _call_openai(self, system: str, user: str, max_tokens: int = 4096) -> str:
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

    async def _call_local(self, system: str, user: str, max_tokens: int = 4096) -> str:
        """Run inference on a local model via mlx-lm (macOS) or llama-cpp-python (Linux)."""
        import sys

        if sys.platform == "darwin":
            return await self._call_mlx(system, user, max_tokens)
        else:
            return await self._call_llama_cpp(system, user, max_tokens)

    async def _call_mlx(self, system: str, user: str, max_tokens: int = 4096) -> str:
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
            max_tokens=max_tokens,
            sampler=sampler,
            verbose=False,
        )
        return response

    async def _call_llama_cpp(self, system: str, user: str, max_tokens: int = 4096) -> str:
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
            max_tokens=max_tokens,
            temperature=self.temperature,
        )
        return response["choices"][0]["message"]["content"]

    async def _call_llm(self, system: str, user: str, max_tokens: int = 4096) -> str:
        # Backend-aware API-key precheck. The OpenAI SDK is reused for the
        # `deepseek` backend; without this guard, its own error message would
        # talk about `OPENAI_API_KEY` regardless of which backend the user
        # actually picked. Keys live exclusively on the FE (Settings → API
        # Keys, persisted to localStorage and sent with each request).
        if self.backend in ("anthropic", "openai", "deepseek") and not self.api_key:
            raise RuntimeError(
                f"{self.backend} API key is missing. Open Settings → API "
                f"Keys in the web UI and save your {self.backend} key, then "
                f"retry — the UI sends it with every request."
            )

        if self.backend == "anthropic":
            return await self._call_anthropic(system, user, max_tokens)
        elif self.backend == "openai":
            return await self._call_openai(system, user, max_tokens)
        elif self.backend == "deepseek":
            if not self.base_url:
                self.base_url = "https://api.deepseek.com/v1"
            return await self._call_openai(system, user, max_tokens)
        elif self.backend == "local":
            return await self._call_local(system, user, max_tokens)
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

        Sends all segments in a single LLM call for full narrative context.
        For very long videos (>full_document_threshold), uses smart chunking
        where each chunk sees the full transcript as context.

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
        non_empty_segments = [seg for _, seg in non_empty]
        non_empty_indices = [idx for idx, _ in non_empty]

        system_prompt = self._build_system_prompt(profile)
        translations: dict[int, str] = {}
        max_tokens = self._estimate_max_tokens(len(non_empty))

        if len(non_empty) <= self.full_document_threshold:
            # FULL DOCUMENT MODE — single LLM call with all segments
            logger.info(
                f"Translating {len(non_empty)} segments in single call "
                f"({profile.name}, {self.backend}/{self.model})"
            )

            if progress_callback:
                progress_callback(1, 1, f"Translating all {len(non_empty)} segments...")

            user_prompt = self._build_full_document_prompt(non_empty_segments, profile)
            response = await self._call_llm(system_prompt, user_prompt, max_tokens)

            # Build mapping: 1-based prompt number → original segment index
            # Prompt shows "1. text", "2. text", etc. for non-empty segments
            number_to_index = {
                i + 1: orig_idx for i, orig_idx in enumerate(non_empty_indices)
            }
            translations = self._parse_numbered_response(response, number_to_index)

            # Retry once if too many missing (>20%)
            missing_count = len(non_empty_indices) - len(translations)
            if missing_count > len(non_empty_indices) * 0.2:
                logger.warning(
                    f"Missing {missing_count}/{len(non_empty_indices)} translations. "
                    "Retrying with stricter instructions..."
                )
                retry_prompt = (
                    user_prompt
                    + f"\n\nIMPORTANT: You MUST return exactly {len(non_empty)} numbered lines, "
                    "no more, no less. One translation per numbered line."
                )
                response = await self._call_llm(system_prompt, retry_prompt, max_tokens)
                translations = self._parse_numbered_response(response, number_to_index)
        else:
            # CHUNKED MODE — full context, partial translation per chunk
            chunks = self._find_natural_chunk_boundaries(non_empty_segments, self.chunk_size)
            total_chunks = len(chunks)

            logger.info(
                f"Translating {len(non_empty)} segments in {total_chunks} chunks "
                f"({profile.name}, {self.backend}/{self.model})"
            )

            for chunk_num, chunk_local_indices in enumerate(chunks, 1):
                msg = f"Translating chunk {chunk_num}/{total_chunks}..."
                if progress_callback:
                    progress_callback(chunk_num, total_chunks, msg)
                logger.info(msg)

                user_prompt = self._build_chunked_document_prompt(
                    non_empty_segments, chunk_local_indices, profile,
                    previous_translations=translations,
                )
                response = await self._call_llm(system_prompt, user_prompt, max_tokens)

                # Build mapping: 1-based prompt number → original segment index
                # Prompt shows e.g., "51. text" for non_empty_segments[50]
                chunk_number_to_index = {
                    local_idx + 1: non_empty_indices[local_idx]
                    for local_idx in chunk_local_indices
                }
                chunk_translations = self._parse_numbered_response(
                    response, chunk_number_to_index
                )
                translations.update(chunk_translations)

                # Rate limiting between chunks (skip for local models)
                if chunk_num < total_chunks and self.backend != "local":
                    await asyncio.sleep(1)

        # Fill in any missing translations with original text
        for idx in non_empty_indices:
            if idx not in translations:
                translations[idx] = segments[idx]["text"]
                logger.warning(f"Missing translation for segment {idx + 1}, using original")

        # Drop segments the LLM marked as __SKIP__ (OCR noise). Comparison is
        # case-insensitive and exact-string (substring matches are NOT
        # dropped — preserves real content that happens to contain the
        # token). Runs AFTER fill-missing so the warning log above doesn't
        # spuriously fire for indices the LLM intentionally skipped.
        skipped_indices: set[int] = set()
        if self.skip_noise:
            for idx, text in list(translations.items()):
                if text.strip().upper() == "__SKIP__":
                    skipped_indices.add(idx)
                    del translations[idx]
            if skipped_indices:
                logger.info(
                    f"Dropped {len(skipped_indices)} noise segments via __SKIP__ marker"
                )

        # Reassemble all segments with translations
        translated_segments = []
        for i, seg in enumerate(segments):
            if i in skipped_indices:
                continue  # noise segment — drop from final SRT entirely
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

    async def shorten_text(
        self,
        text: str,
        target_ratio: float,
        language: str | None = None,
        current_duration: float | None = None,
        target_duration: float | None = None,
        speed_ratio: float | None = None,
    ) -> str:
        """Shorten text for TTS timing, preserving core meaning.

        Args:
            text: Original subtitle text.
            target_ratio: Target length as fraction of original (e.g., 0.6 = 60%).
            language: Optional language hint.
            current_duration: How long the TTS audio currently is (seconds).
            target_duration: How long the audio needs to fit into (seconds).
            speed_ratio: Current speedup ratio (e.g., 2.5 means 2.5x too long).

        Returns:
            Shortened text, or original if shortening fails.
        """
        target_pct = max(30, int(target_ratio * 100))
        lang_hint = f" The text is in {language}." if language else ""

        timing_context = ""
        if current_duration and target_duration and speed_ratio:
            timing_context = (
                f"\n\nTiming context: The TTS audio for this text is {current_duration:.1f}s "
                f"but must fit in {target_duration:.1f}s ({speed_ratio:.1f}x too long). "
                f"The shortened version needs to be spoken in under {target_duration:.1f}s. "
                f"Be aggressive — remove filler words, simplify phrases, keep only the essential meaning."
            )

        system = (
            "You are a subtitle editor optimizing text for TTS dubbing. "
            "Shorten subtitle text so it can be spoken faster while preserving core meaning. "
            "Output must be natural speech suitable for text-to-speech."
        )
        user = (
            f"Shorten this text to approximately {target_pct}% of its current spoken length. "
            f"Keep the core meaning but make it much more concise. "
            f"Return ONLY the shortened text, nothing else.{lang_hint}{timing_context}\n\n"
            f"Original: {text}"
        )

        try:
            logger.info(
                f"Shortening text: '{text[:60]}' | "
                f"duration={current_duration:.1f}s → target={target_duration:.1f}s "
                f"({speed_ratio:.1f}x) | target_pct={target_pct}%"
                if current_duration and target_duration and speed_ratio
                else f"Shortening text: '{text[:60]}' | target_pct={target_pct}%"
            )
            result = await self._call_llm(system, user)
            shortened = result.strip().split("\n")[0].strip()
            if not shortened or len(shortened) >= len(text):
                logger.info(f"Shortening produced no improvement, keeping original")
                return text
            logger.info(f"Shortened: '{text[:40]}' → '{shortened[:40]}' ({len(text)}→{len(shortened)} chars)")
            return shortened
        except Exception as e:
            logger.warning(f"Text shortening failed: {e}")
            return text

    async def shorten_texts_batch(
        self,
        items: list[dict],
    ) -> list[str]:
        """Shorten multiple texts in a single LLM call.

        Args:
            items: List of dicts with keys: text, target_pct, current_duration, target_duration, speed_ratio

        Returns:
            List of shortened texts (same order as input). Falls back to original on failure.
        """
        if not items:
            return []

        lines = []
        for i, item in enumerate(items):
            lines.append(
                f"{i + 1}. [{item['current_duration']:.1f}s→{item['target_duration']:.1f}s, {item['speed_ratio']:.1f}x] {item['text']}"
            )

        system = (
            "You are a subtitle editor optimizing text for TTS dubbing. "
            "Shorten each subtitle line so it can be spoken in the target duration. "
            "Trim only what's necessary to fit the target — preserve full meaning "
            "and natural phrasing. Aim for the longest version that still fits. "
            "Do not collapse a sentence to a fragment."
        )
        user = (
            f"Shorten each of the following {len(items)} subtitle lines. "
            f"Each line shows [current_duration→target_duration, speedup_ratio] followed by the text. "
            f"Return EXACTLY {len(items)} lines, one shortened version per line, in the same order. "
            f"Return ONLY the shortened text for each line, numbered like '1. shortened text'.\n\n"
            + "\n".join(lines)
        )

        logger.info(f"Batch shortening {len(items)} segments in single LLM call")

        try:
            result = await self._call_llm(system, user)
            parsed = self._parse_shortening_response(result, len(items))

            shortened = []
            for i, item in enumerate(items):
                original = item["text"]
                candidate = parsed[i] if i < len(parsed) else None
                # Per-item floor: respect the target_pct we asked for, with an
                # absolute minimum of 40% to keep enough words to preserve
                # meaning. The TTS assembler runs iterative shortening passes
                # with progressively stricter target_pcts, so an
                # over-aggressive single response (which the assembler
                # rejects here) just gets a stricter target on the next pass.
                target_pct = item.get("target_pct", 100)
                floor_pct = max(40, target_pct - 15)
                floor_chars = max(1, int(len(original) * floor_pct / 100))
                if candidate and len(candidate) < len(original):
                    if len(candidate) < floor_chars:
                        logger.warning(
                            f"  Segment: rejecting over-shortened '{original[:30]}' "
                            f"→ '{candidate[:30]}' "
                            f"({len(candidate)}/{len(original)} chars, "
                            f"floor {floor_pct}%)"
                        )
                        shortened.append(original)
                    else:
                        logger.info(
                            f"  Segment: '{original[:30]}' → '{candidate[:30]}' "
                            f"({item['speed_ratio']:.1f}x)"
                        )
                        shortened.append(candidate)
                else:
                    shortened.append(original)
            return shortened
        except Exception as e:
            logger.warning(f"Batch shortening failed: {e}")
            return [item["text"] for item in items]

    def _parse_shortening_response(self, response: str, expected: int) -> list[str]:
        """Parse numbered lines from LLM response."""
        import re
        lines = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Remove numbering like "1. " or "1) "
            cleaned = re.sub(r"^\d+[\.\)]\s*", "", line).strip()
            if cleaned:
                lines.append(cleaned)
        return lines
