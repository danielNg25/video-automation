# Subtitle Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two narrow source-side fixes for translated subtitle quality — (a) collapse adjacent OCR segments with identical text into one, and (b) tell the translator to mark watermark/handle/noise tokens with `__SKIP__`, then drop those rows from the final SRT.

**Architecture:** Independent changes in two pipeline stages. OCR (`src/transcriber/ocr.py`) gains a small post-processing helper that runs at the end of `_build_segments_from_frames`. Translator (`src/translator/llm.py`) gains a `skip_noise` constructor flag that conditionally adds a SKIP instruction to the system prompt and filters `__SKIP__` translations out of the reassembly loop. Both wired through `config.yaml::translation.skip_noise` (default true) via the existing `get_translator` factory.

**Tech Stack:** Python 3.11, pytest (`pytest-asyncio` auto mode), `unittest.mock.AsyncMock` for stubbing `_call_llm`. No new dependencies.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `src/transcriber/ocr.py` | Add module-level `_merge_consecutive_duplicates(segments)` helper. Call it at the end of `_build_segments_from_frames` so the OCR stage produces no adjacent-text dupes. | **Modify** |
| `tests/test_ocr_dedup.py` | 8 unit tests for the helper. | **Create** |
| `src/translator/llm.py` | `__init__` gains `skip_noise: bool = True`. `_build_system_prompt` conditionally appends the SKIP instruction. `translate_srt` filters `__SKIP__` translations out of the reassembly loop. | **Modify** |
| `tests/test_translator_skip.py` | 4 unit tests for the SKIP flow (prompt-on, prompt-off, drop, substring guard). | **Create** |
| `src/translator/__init__.py` | `get_translator` reads `skip_noise` from config and passes to `LLMTranslator`. | **Modify** |
| `tests/test_translator_factory.py` | 2 tests confirming the factory wiring (default true, explicit false). | **Create** |
| `config/config.example.yaml` | Document `translation.skip_noise: true`. | **Modify** |
| `CHANGELOG.md` | `Added` entry under `[Unreleased]`. | **Modify** |
| `README.md` | New dated subsection in Implementation Progress. | **Modify** |

---

### Task 1: OCR `_merge_consecutive_duplicates` helper + 8 unit tests

**Files:**
- Modify: `src/transcriber/ocr.py`
- Create: `tests/test_ocr_dedup.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_ocr_dedup.py`:

```python
"""Unit tests for OCR-stage consecutive-duplicate-segment merging.

The helper runs at the end of _build_segments_from_frames; it collapses
runs of adjacent segments whose text is identical (after .strip()) into
a single segment spanning start[first] to end[last]. Non-adjacent
duplicates are left alone — they're distinct spoken moments.
"""

from __future__ import annotations

from src.transcriber.ocr import _merge_consecutive_duplicates


def _seg(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "text": text}


class TestMergeConsecutiveDuplicates:
    def test_empty_input_returns_empty(self):
        assert _merge_consecutive_duplicates([]) == []

    def test_single_segment_returned_unchanged(self):
        segs = [_seg(0.0, 1.0, "a")]
        assert _merge_consecutive_duplicates(segs) == segs

    def test_no_duplicates_passes_through(self):
        segs = [
            _seg(0.0, 1.0, "alpha"),
            _seg(1.0, 2.0, "beta"),
            _seg(2.0, 3.0, "gamma"),
        ]
        assert _merge_consecutive_duplicates(segs) == segs

    def test_two_adjacent_dupes_merge_with_spanning_timing(self):
        out = _merge_consecutive_duplicates([
            _seg(0.0, 1.0, "你好"),
            _seg(2.0, 3.0, "你好"),
        ])
        assert out == [_seg(0.0, 3.0, "你好")]

    def test_three_plus_adjacent_dupes_collapse(self):
        out = _merge_consecutive_duplicates([
            _seg(0.0, 1.0, "你好"),
            _seg(1.0, 2.0, "你好"),
            _seg(2.0, 3.0, "你好"),
        ])
        assert out == [_seg(0.0, 3.0, "你好")]

    def test_non_adjacent_dupes_kept_separate(self):
        segs = [
            _seg(0.0, 1.0, "你好"),
            _seg(1.0, 2.0, "再见"),
            _seg(2.0, 3.0, "你好"),
        ]
        assert _merge_consecutive_duplicates(segs) == segs

    def test_strip_handles_whitespace_differences(self):
        out = _merge_consecutive_duplicates([
            _seg(0.0, 1.0, "hello"),
            _seg(1.0, 2.0, "hello "),
            _seg(2.0, 3.0, " hello"),
        ])
        assert out == [_seg(0.0, 3.0, "hello")]

    def test_empty_text_segments_not_merged(self):
        """Two adjacent empty-text segments stay as two entries. Empty
        matching empty isn't a meaningful 'duplicate spoken moment'; the
        existing downstream stages already filter empty text where
        appropriate, so leave them alone here."""
        segs = [
            _seg(0.0, 1.0, ""),
            _seg(1.0, 2.0, ""),
        ]
        assert _merge_consecutive_duplicates(segs) == segs
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ocr_dedup.py -v 2>&1 | tail -10`
Expected: `ImportError: cannot import name '_merge_consecutive_duplicates' from 'src.transcriber.ocr'`.

- [ ] **Step 1.3: Add the helper to `src/transcriber/ocr.py`**

Find `_build_segments_from_frames` (the existing method that ends with `return segments` around line 604). Add the new helper as a module-level function (NOT a method) right after the class containing `_build_segments_from_frames`. Insert this block somewhere after the class definition closes:

```python
def _merge_consecutive_duplicates(segments: list[dict]) -> list[dict]:
    """Collapse runs of consecutive segments whose text is identical
    (after .strip()) into a single segment spanning start[first] to
    end[last]. Non-adjacent duplicates (e.g. segment 3 and segment 11
    both saying 'hello') are left alone — they're distinct spoken
    moments.

    Empty-text segments are left untouched; empty matching empty isn't
    a meaningful duplicate.
    """
    if not segments:
        return []

    out: list[dict] = [dict(segments[0])]
    for seg in segments[1:]:
        last = out[-1]
        cur_text = seg["text"].strip()
        last_text = last["text"].strip()
        if cur_text and cur_text == last_text:
            # Extend the previous segment's end to swallow this one.
            last["end"] = seg["end"]
            continue
        out.append(dict(seg))
    return out
```

(The `dict(...)` copies are defensive so we don't mutate the caller's segments.)

- [ ] **Step 1.4: Wire the helper into `_build_segments_from_frames`**

At the end of `_build_segments_from_frames`, change:

```python
        logger.info(
            f"OCR produced {len(segments)} segments from {len(frame_texts)} frames"
        )
        return segments
```

to:

```python
        merged = _merge_consecutive_duplicates(segments)
        if len(merged) < len(segments):
            logger.info(
                f"OCR produced {len(segments)} segments from {len(frame_texts)} frames; "
                f"merged {len(segments) - len(merged)} consecutive-duplicate segments → "
                f"{len(merged)} final"
            )
        else:
            logger.info(
                f"OCR produced {len(segments)} segments from {len(frame_texts)} frames"
            )
        return merged
```

- [ ] **Step 1.5: Run tests to verify they pass**

Run: `python -m pytest tests/test_ocr_dedup.py -v 2>&1 | tail -12`
Expected: 8 passed.

- [ ] **Step 1.6: Lint clean**

Run: `ruff check src/transcriber/ocr.py tests/test_ocr_dedup.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 1.7: Commit**

```bash
git add src/transcriber/ocr.py tests/test_ocr_dedup.py
git commit -m "feat(ocr): merge consecutive duplicate segments

The existing OCR loop already dedups similar text across consecutive
FRAMES via SequenceMatcher, but that operates inside a single
segment-building pass. When an empty frame closes a segment and the
SAME text reappears in the next non-empty frame, the loop opens a
fresh segment — producing two adjacent SRT rows with identical text.
The translated output then shows the same line repeated 2-3x.

_merge_consecutive_duplicates walks the segment list once and
collapses runs of segments whose .strip()'d text matches into a
single segment spanning [start_first, end_last]. Non-adjacent
duplicates are kept separate (they're distinct spoken moments).
Empty-text segments don't match each other (empty isn't a meaningful
duplicate).

Wired into _build_segments_from_frames as the final step. 8 unit
tests cover the helper end-to-end."
```

---

### Task 2: Translator `skip_noise` flag + SKIP filter + 4 unit tests

**Files:**
- Modify: `src/translator/llm.py`
- Create: `tests/test_translator_skip.py`

- [ ] **Step 2.1: Write the failing tests**

Create `tests/test_translator_skip.py`:

```python
"""Unit tests for the translator's __SKIP__ noise-removal flow.

skip_noise=True (default): the system prompt instructs the LLM to
mark OCR noise (watermarks, handles, etc.) as the literal __SKIP__.
The post-parse filter drops those segments entirely from the output
SRT — surrounding segments keep their original timings.

skip_noise=False: the prompt is unchanged and no filtering happens.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.processor.subtitle import parse_srt, write_srt
from src.translator.llm import LLMTranslator
from src.translator.profiles import TranslationProfile


def _profile() -> TranslationProfile:
    return TranslationProfile(
        name="test",
        description="",
        target_language="vi",
        source_language="zh",
        style_guide="Be casual.",
        example_pairs=[],
    )


class TestSkipInstructionInPrompt:
    def test_skip_instruction_appended_when_flag_on(self):
        t = LLMTranslator(skip_noise=True, api_key="x")
        prompt = t._build_system_prompt(_profile())
        assert "__SKIP__" in prompt
        assert "watermark" in prompt.lower() or "handle" in prompt.lower()

    def test_skip_instruction_omitted_when_flag_off(self):
        t = LLMTranslator(skip_noise=False, api_key="x")
        prompt = t._build_system_prompt(_profile())
        assert "__SKIP__" not in prompt


class TestSkipFiltering:
    @pytest.mark.asyncio
    async def test_translate_srt_drops_skip_segments(self, tmp_path: Path):
        """5-segment SRT, LLM marks segments 2 and 4 as __SKIP__ → output
        SRT contains only segments 1, 3, 5 with their original timings."""
        src = tmp_path / "in.srt"
        write_srt(
            [
                {"start": 0.0, "end": 1.0, "text": "real one"},
                {"start": 1.0, "end": 2.0, "text": "@channel_handle"},
                {"start": 2.0, "end": 3.0, "text": "real three"},
                {"start": 3.0, "end": 4.0, "text": "watermark text"},
                {"start": 4.0, "end": 5.0, "text": "real five"},
            ],
            src,
        )
        out = tmp_path / "out.srt"
        t = LLMTranslator(skip_noise=True, api_key="x")

        # The LLM's full-document response format is "N. translated text"
        # per non-empty input line. Mark lines 2 and 4 as __SKIP__.
        llm_response = (
            "1. translated one\n"
            "2. __SKIP__\n"
            "3. translated three\n"
            "4. __SKIP__\n"
            "5. translated five\n"
        )

        with patch.object(t, "_call_llm", new=AsyncMock(return_value=llm_response)):
            await t.translate_srt(src, _profile(), out)

        result = parse_srt(out)
        assert len(result) == 3
        assert result[0]["text"] == "translated one"
        assert result[0]["start"] == 0.0 and result[0]["end"] == 1.0
        assert result[1]["text"] == "translated three"
        assert result[1]["start"] == 2.0 and result[1]["end"] == 3.0
        assert result[2]["text"] == "translated five"
        assert result[2]["start"] == 4.0 and result[2]["end"] == 5.0

    @pytest.mark.asyncio
    async def test_skip_marker_substring_in_real_translation_kept(self, tmp_path: Path):
        """If the LLM accidentally embeds '__SKIP__' inside a real
        translation, the exact-match filter does NOT drop the row."""
        src = tmp_path / "in.srt"
        write_srt(
            [
                {"start": 0.0, "end": 1.0, "text": "hi"},
                {"start": 1.0, "end": 2.0, "text": "bye"},
            ],
            src,
        )
        out = tmp_path / "out.srt"
        t = LLMTranslator(skip_noise=True, api_key="x")

        llm_response = (
            "1. this is __SKIP__ adjacent text\n"
            "2. translated bye\n"
        )

        with patch.object(t, "_call_llm", new=AsyncMock(return_value=llm_response)):
            await t.translate_srt(src, _profile(), out)

        result = parse_srt(out)
        assert len(result) == 2
        assert "__SKIP__" in result[0]["text"]
        assert result[1]["text"] == "translated bye"
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `python -m pytest tests/test_translator_skip.py -v 2>&1 | tail -15`
Expected: `TypeError: __init__() got an unexpected keyword argument 'skip_noise'` (or similar — `skip_noise` not yet a parameter).

- [ ] **Step 2.3: Add `skip_noise` to `LLMTranslator.__init__`**

In `src/translator/llm.py`, find the `__init__` method (around line 22). It currently looks like:

```python
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
    ):
        self.backend = backend
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_segments_per_batch = max_segments_per_batch
        self.full_document_threshold = full_document_threshold
        self.chunk_size = chunk_size
        self.temperature = temperature
        self._client = None
```

Add `skip_noise: bool = True` as the new last parameter and store it. Result:

```python
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
```

- [ ] **Step 2.4: Conditionally append SKIP instruction in `_build_system_prompt`**

Find `_build_system_prompt` (around line 43). It currently looks like:

```python
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
```

Just before `return "\n".join(parts)`, append the SKIP block (gated on the flag):

```python
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
```

- [ ] **Step 2.5: Filter SKIP entries in `translate_srt`**

In `src/translator/llm.py`, find the "Fill in any missing translations with original text" block (around line 534). It currently looks like:

```python
        # Fill in any missing translations with original text
        for idx in non_empty_indices:
            if idx not in translations:
                translations[idx] = segments[idx]["text"]
                logger.warning(f"Missing translation for segment {idx + 1}, using original")

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
```

Insert a SKIP-filter block right after the fill-missing loop and before the reassembly loop, and add the `if i in skipped_indices: continue` guard inside reassembly:

```python
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
```

- [ ] **Step 2.6: Run tests to verify they pass**

Run: `python -m pytest tests/test_translator_skip.py -v 2>&1 | tail -15`
Expected: 4 passed.

- [ ] **Step 2.7: Lint clean**

Run: `ruff check src/translator/llm.py tests/test_translator_skip.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 2.8: Commit**

```bash
git add src/translator/llm.py tests/test_translator_skip.py
git commit -m "feat(translator): __SKIP__ marker drops OCR-noise rows from output SRT

LLMTranslator.__init__ gains skip_noise: bool = True. When the flag
is on (default):

- _build_system_prompt appends a clause telling the LLM that some
  inputs are OCR noise (channel handles, watermark text, random
  fragments) and should be marked with the literal __SKIP__ instead
  of translated. Full-document context lets the LLM judge what's
  real vs noise.
- translate_srt scans the translations dict after the existing
  fill-missing block and drops any entry whose value (after strip
  and upper) equals __SKIP__. The reassembly loop then skips those
  source indices entirely; surrounding segments keep their original
  timings.

Match is exact-string after .strip().upper() — substring matches
(e.g. real translations that mention '__SKIP__') are kept as-is.

With skip_noise=False, the prompt and filter are both no-ops;
behavior is unchanged from today. 4 unit tests cover prompt-on /
prompt-off / drop happy path / substring guard."
```

---

### Task 3: Factory wire-up + config docs + 2 factory tests

**Files:**
- Modify: `src/translator/__init__.py`
- Create: `tests/test_translator_factory.py`
- Modify: `config/config.example.yaml`

- [ ] **Step 3.1: Write the failing factory tests**

Create `tests/test_translator_factory.py`:

```python
"""Unit tests for get_translator wiring the skip_noise flag from config."""

from __future__ import annotations

from src.translator import get_translator


class TestSkipNoiseConfigWiring:
    def test_default_true_when_key_absent(self):
        """skip_noise defaults to True when the config doesn't set it."""
        cfg = {"translation": {"backend": "anthropic", "api_key": "x"}}
        t = get_translator(cfg)
        assert t.skip_noise is True

    def test_respects_explicit_false(self):
        """A user can opt out via translation.skip_noise: false."""
        cfg = {
            "translation": {
                "backend": "anthropic",
                "api_key": "x",
                "skip_noise": False,
            }
        }
        t = get_translator(cfg)
        assert t.skip_noise is False
```

- [ ] **Step 3.2: Run to verify they fail**

Run: `python -m pytest tests/test_translator_factory.py -v 2>&1 | tail -10`
Expected: `AssertionError: assert <something other than True>` or similar — `get_translator` doesn't yet read `skip_noise`.

- [ ] **Step 3.3: Wire the flag through `get_translator`**

Open `src/translator/__init__.py`. The factory currently looks like:

```python
def get_translator(config: dict) -> LLMTranslator:
    """Factory: return a configured LLM translator from config['translation']."""
    trans_cfg = config.get("translation", {})
    return LLMTranslator(
        backend=trans_cfg.get("backend", "anthropic"),
        model=trans_cfg.get("model", "claude-sonnet-4-20250514"),
        api_key=trans_cfg.get("api_key"),
        base_url=trans_cfg.get("base_url"),
        max_segments_per_batch=trans_cfg.get("max_segments_per_batch", 8),
        full_document_threshold=trans_cfg.get("full_document_threshold", 100),
        chunk_size=trans_cfg.get("chunk_size", 50),
        temperature=trans_cfg.get("temperature", 0.7),
    )
```

Add `skip_noise=trans_cfg.get("skip_noise", True)` as the new last argument:

```python
def get_translator(config: dict) -> LLMTranslator:
    """Factory: return a configured LLM translator from config['translation']."""
    trans_cfg = config.get("translation", {})
    return LLMTranslator(
        backend=trans_cfg.get("backend", "anthropic"),
        model=trans_cfg.get("model", "claude-sonnet-4-20250514"),
        api_key=trans_cfg.get("api_key"),
        base_url=trans_cfg.get("base_url"),
        max_segments_per_batch=trans_cfg.get("max_segments_per_batch", 8),
        full_document_threshold=trans_cfg.get("full_document_threshold", 100),
        chunk_size=trans_cfg.get("chunk_size", 50),
        temperature=trans_cfg.get("temperature", 0.7),
        skip_noise=trans_cfg.get("skip_noise", True),
    )
```

- [ ] **Step 3.4: Document the flag in `config/config.example.yaml`**

Find the `translation:` block (around line 16). It currently ends with `default_profile: 'funny-casual-vi'`. Append:

```yaml
    # When true (default), the translator is instructed to mark OCR noise
    # (watermarks, channel handles, stray fragments) with __SKIP__. Those
    # segments are then dropped from the final SRT entirely. Set false if
    # you find it removing legit content.
    skip_noise: true
```

Result (the relevant block):

```yaml
translation:
    backend: 'anthropic'                    # "anthropic" | "openai" | "deepseek"
    model: 'claude-sonnet-4-20250514'       # model ID
    full_document_threshold: 100         # single LLM call up to this many segments
    chunk_size: 50                       # segments per chunk when exceeding threshold
    temperature: 0.7
    default_profile: 'funny-casual-vi'
    # When true (default), the translator is instructed to mark OCR noise
    # (watermarks, channel handles, stray fragments) with __SKIP__. Those
    # segments are then dropped from the final SRT entirely. Set false if
    # you find it removing legit content.
    skip_noise: true
```

- [ ] **Step 3.5: Run factory tests to verify they pass**

Run: `python -m pytest tests/test_translator_factory.py -v 2>&1 | tail -10`
Expected: 2 passed.

- [ ] **Step 3.6: Run the full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -5`
Expected: green. Roughly +14 tests over the baseline (8 OCR dedup + 4 translator skip + 2 factory).

- [ ] **Step 3.7: Lint clean**

Run: `ruff check src/translator/__init__.py tests/test_translator_factory.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 3.8: Commit**

```bash
git add src/translator/__init__.py tests/test_translator_factory.py config/config.example.yaml
git commit -m "feat(translator): wire skip_noise through get_translator + document config

get_translator reads translation.skip_noise from the config dict
(default true) and passes it to LLMTranslator. Two unit tests
confirm the wiring: default True when the key is absent, and
respects an explicit False for opt-out.

config.example.yaml documents the new flag under the existing
translation: block with the user-facing description: 'When true
(default), the translator is instructed to mark OCR noise … Set
false if you find it removing legit content.'"
```

---

### Task 4: CHANGELOG + README rollup

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 4.1: CHANGELOG entry**

Open `CHANGELOG.md`. Find `## [Unreleased]` → `### Added`. Add this entry at the top of the `Added` block:

```markdown
- **Subtitle cleanup: OCR dedup + translator `__SKIP__` for noise.** Two narrow source-side fixes for translated subtitle quality. (1) `src/transcriber/ocr.py` gains `_merge_consecutive_duplicates` — collapses runs of adjacent OCR segments with identical text (after `.strip()`) into a single segment spanning the combined timing. Fixes the "same line repeated 2-3× back-to-back" case where an empty frame between two same-text runs split them. Non-adjacent dupes are kept separate (distinct spoken moments). (2) `LLMTranslator` gains `skip_noise: bool = True`. When on, the system prompt instructs the LLM to mark OCR noise (channel handles like `@user` / `抖音号:`, watermarks, stray fragments) with the literal `__SKIP__`; the post-parse filter drops those rows from the output SRT entirely. Exact-string match after `strip().upper()` — substring matches are NOT dropped. Gated by `translation.skip_noise: true` in `config.yaml` (default on, opt-out only). 14 new tests (8 OCR + 4 translator + 2 factory). No new LLM calls.
```

- [ ] **Step 4.2: README progress section**

Open `README.md`. Find the most recent dated subsection under Implementation Progress. Insert this new subsection immediately after its `---` separator:

```markdown
### Subtitle cleanup: OCR dedup + translator __SKIP__ (2026-06-03)

> Two narrow source-side fixes for translated subtitle quality. See [`docs/superpowers/specs/2026-06-03-subtitle-cleanup-design.md`](docs/superpowers/specs/2026-06-03-subtitle-cleanup-design.md) and [`docs/superpowers/plans/2026-06-03-subtitle-cleanup.md`](docs/superpowers/plans/2026-06-03-subtitle-cleanup.md).

- [x] **Task 1** — `src/transcriber/ocr.py::_merge_consecutive_duplicates`: collapses runs of adjacent same-text OCR segments into one with spanning timing. Wired into `_build_segments_from_frames`'s final step. 8 unit tests.
- [x] **Task 2** — `src/translator/llm.py`: `LLMTranslator.__init__` gains `skip_noise: bool = True`; `_build_system_prompt` conditionally appends the `__SKIP__` instruction; `translate_srt` filters SKIP entries before reassembly (exact-string match after `.strip().upper()`). 4 unit tests.
- [x] **Task 3** — Factory + config wire-up: `get_translator` reads `translation.skip_noise` (default true); `config.example.yaml` documents the flag. 2 factory tests.
- [x] **Task 4** — CHANGELOG + README updates.

---
```

- [ ] **Step 4.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(subtitle-cleanup): CHANGELOG + README rollup"
```

---

## Final verification (run before reporting DONE)

- [ ] **Step F.1: Full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -5`
Expected: green. +14 tests over baseline (8 OCR + 4 translator + 2 factory).

- [ ] **Step F.2: BE lint on every touched file**

```bash
ruff check src/transcriber/ocr.py src/translator/llm.py src/translator/__init__.py \
  tests/test_ocr_dedup.py tests/test_translator_skip.py tests/test_translator_factory.py \
  2>&1 | tail -3
```
Expected: `All checks passed!`

- [ ] **Step F.3: Manual smoke (after merge)**

1. Pipeline a Douyin video known to produce adjacent-text dupes → check `data/srt/{id}_zh.srt` — no adjacent identical lines.
2. The same video has a visible channel handle / watermark → check the translated SRT (`{id}_vi.srt`) — those lines should be absent.
3. Set `translation.skip_noise: false` in `config.yaml`, re-translate (or just re-run translate stage) → noise lines should reappear (proves the gating works end-to-end).
4. Check the pipeline log: should see `Merged N consecutive-duplicate segments` from OCR and `Dropped N noise segments via __SKIP__ marker` from the translator.

---

## Self-review checklist (for the implementer)

- [ ] Spec coverage: each section in the spec maps to a task (OCR helper → T1, translator flag + filter → T2, factory + config → T3, docs → T4).
- [ ] No "TBD" / "implement later" / "similar to Task N" anywhere.
- [ ] Type/name consistency: `_merge_consecutive_duplicates`, `skip_noise`, `__SKIP__`, `skipped_indices` used identically across plan tasks and the spec.
- [ ] `__SKIP__` literal is exact (uppercase, double underscores) in prompt + filter + tests + docs.
- [ ] Match check is `text.strip().upper() == "__SKIP__"` everywhere (case-insensitive, exact-string).
- [ ] No new branches mid-plan; all work lands on `feature/subtitle-cleanup`.
- [ ] No AI-attribution strings in any commit message.
- [ ] CHANGELOG entry under `Added` in `[Unreleased]`.
- [ ] README entry next to other dated subsections, not at the bottom.
