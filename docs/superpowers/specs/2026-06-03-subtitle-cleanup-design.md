# Subtitle cleanup: OCR dedup + translator SKIP for noise

## Goal

Two narrow, source-side fixes for translated subtitle quality:

1. **Drop consecutive duplicate OCR segments** that today land in the SRT as `[start1→end1, "你好"]` `[start2→end2, "你好"]` because an empty frame between two same-text runs splits them.
2. **Tell the translator to skip watermark / channel-handle / OCR-noise tokens** by returning a sentinel (`__SKIP__`) which the post-processor drops from the final SRT.

No extra LLM calls. Two small code changes plus a config flag.

## Why

The user observed (a) same line repeated 2–3× back-to-back in translations, and (b) random tokens like watermark text / channel handles leaking through. Both originate at OCR; both have cheap deterministic-ish fixes that don't add a second full-document LLM call.

## Non-goals

- **Second LLM "review" pass** after translation. Explicitly ruled out during brainstorming — costs another full-document call.
- **Fuzzy dedup at segment level.** Frame-level fuzzy already exists (`SequenceMatcher` in `_build_segments_from_frames`). Segment-level uses exact match only to avoid swallowing short legit lines that happen to be similar (e.g. "Hi" and "Hey").
- **Auto-skip by regex / character class.** Channel handles take many shapes (Latin `@user`, Chinese `抖音号:xyz`, emoji-prefixed, etc.). LLM judgment with full-document context beats a fragile pattern list.
- **Cross-segment dedup** (line 3 and line 11 both say "hello" → keep both). They're distinct spoken moments.
- **Modifying the OCR similarity threshold or other detection heuristics.** This work assumes existing OCR behavior and adds a small post-processing step.

## Architecture

Two completely independent code changes — different files, different stages, no shared abstraction.

```
       ┌──────────────────────────────────────────────────┐
       │ OCR transcribe stage                             │
       │ src/transcriber/ocr.py                           │
       │                                                  │
       │  _build_segments_from_frames(...)  (existing)    │
       │              │                                   │
       │              ▼                                   │
       │  _merge_consecutive_duplicates(segs) ← NEW       │
       │       collapse runs of exact-match text          │
       │              │                                   │
       │              ▼                                   │
       │       returns deduped segment list               │
       └──────────────────────────────────────────────────┘
                              │
                              ▼   data/srt/{id}_zh.srt (deduped)
       ┌──────────────────────────────────────────────────┐
       │ Translate stage                                  │
       │ src/translator/llm.py                            │
       │                                                  │
       │  __init__: + skip_noise: bool = True             │
       │                                                  │
       │  _build_system_prompt(...)                       │
       │     + (if skip_noise) append SKIP instruction    │
       │                                                  │
       │  translate_srt(...)                              │
       │     after parsing translations:                  │
       │       filter out entries == '__SKIP__'           │
       │     reassembly loop:                             │
       │       drop segments whose translation was SKIP   │
       └──────────────────────────────────────────────────┘
                              │
                              ▼   data/srt/{id}_vi.srt (no SKIPs, no dupes)
```

Two indirections from config: `translation.skip_noise: true` (default) → `get_translator()` reads it → `LLMTranslator(skip_noise=...)`.

## Components

### `src/transcriber/ocr.py` — add `_merge_consecutive_duplicates`

Append a small helper after `_build_segments_from_frames` (around line 604) and call it on that function's return value.

```python
def _merge_consecutive_duplicates(segments: list[dict]) -> list[dict]:
    """Collapse runs of consecutive segments whose text is identical
    (after .strip()) into a single segment spanning start[first] to
    end[last]. Non-adjacent duplicates (e.g. segment 3 and segment 11
    both saying 'hello') are left alone — they're distinct spoken
    moments.

    Empty-text segments are left untouched; empty doesn't match empty
    in a meaningful way here, and downstream stages already filter
    empties.
    """
```

Behaviour:
- Walk segments once.
- If `segments[i]["text"].strip() == segments[i+1]["text"].strip()` and the text is non-empty, merge: keep `segments[i]["start"]`, replace its `end` with `segments[i+1]["end"]`. Drop `segments[i+1]`. Continue from the same `i` so a run of 3+ collapses.
- Return the new list.

Wire-up: at the end of `_build_segments_from_frames`, change `return segments` to `return _merge_consecutive_duplicates(segments)`. Log `Merged N consecutive-duplicate segments` when N > 0.

### `src/translator/llm.py` — SKIP instruction + filter

**Constructor**: add `skip_noise: bool = True` parameter, store on `self.skip_noise`.

**`_build_system_prompt`**: when `self.skip_noise` is True, append after the existing parts:

```
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
```

When `self.skip_noise` is False, no instruction is appended (existing behavior preserved).

**`translate_srt`**: after the existing "fill missing translations with original text" block (line ~538), drop SKIP entries. Doing it AFTER fill-missing avoids the fill loop logging a spurious warning for indices that the LLM intentionally SKIP'd. Comparison is case-insensitive so a stray `__skip__` from the LLM still gets caught:

```python
skipped_indices: set[int] = set()
for idx, text in list(translations.items()):
    if text.strip().upper() == "__SKIP__":
        skipped_indices.add(idx)
        del translations[idx]
```

In the reassembly loop (lines 540-549), filter out skipped indices entirely (don't append to `translated_segments`):

```python
translated_segments = []
for i, seg in enumerate(segments):
    if i in skipped_indices:
        continue  # drop noise segment from final SRT
    translated_segments.append({
        "start": seg["start"],
        "end": seg["end"],
        "text": translations.get(i, seg["text"]) if i not in empty_indices else "",
    })
```

Log `f"Dropped {len(skipped_indices)} noise segments via __SKIP__ marker"` when N > 0.

### `src/translator/__init__.py` — pass flag through

In `get_translator`, read the flag from config (default True) and pass to constructor:

```python
return LLMTranslator(
    backend=trans_cfg.get("backend", "anthropic"),
    model=trans_cfg.get("model", "claude-sonnet-4-20250514"),
    # ... existing args ...
    skip_noise=trans_cfg.get("skip_noise", True),
)
```

### `config/config.example.yaml` — document the flag

Add under the `translation:` section:

```yaml
translation:
  # ...existing keys...
  # When true (default), the translator is instructed to mark OCR noise
  # (watermarks, channel handles, stray fragments) with __SKIP__. Those
  # segments are then dropped from the final SRT entirely. Set false if
  # you find it removing legit content.
  skip_noise: true
```

## Data flow

```
OCR
  frames → _build_segments_from_frames → [seg₀, seg₁, seg₂, seg₃, …]
                                                ↓
                              _merge_consecutive_duplicates
                                                ↓
                              [seg₀,    seg₁₂₃,    …]
                              (seg₁/₂/₃ had identical text → merged)
                                                ↓
                              write to data/srt/{id}_zh.srt

Translate
  parse_srt(data/srt/{id}_zh.srt) → segments
  build_system_prompt(profile, skip_noise=True)  ← adds __SKIP__ clause
  build_user_prompt → LLM call → response
  parse → translations dict
  filter: drop entries whose value == "__SKIP__"
  reassemble: skip those source indices entirely
  write to data/srt/{id}_vi.srt
```

## Behavior

| Scenario | Result |
|---|---|
| OCR captures `你好` in frames 1+2, empty in 3, `你好` again in 4+5 | One merged segment `[start_f1 → end_f5, 你好]` instead of two adjacent dupes. |
| OCR captures 3 consecutive segments all `你好` | All three merge into one with combined span. |
| OCR captures `你好` (seg 3) and `你好` (seg 11) with different text between | Both kept — non-adjacent, not duplicates in the sense we care about. |
| Source line is `@channel_handle` | LLM returns `__SKIP__`; row dropped from final SRT. |
| Source line is `抖音号: abc123` | Same — dropped. |
| LLM returns `__SKIP__` for a legit line | User disables via `translation.skip_noise: false` in config; redo. |
| `skip_noise: false` | Prompt unchanged from today; no filtering. Existing behavior preserved. |
| `__SKIP__` appears in the middle of a real translation (e.g. user content includes "__SKIP__" verbatim) | The filter checks `text.strip() == "__SKIP__"` exactly — substrings don't match. Real content containing the token isn't dropped. |
| Multiple `__SKIP__` segments | All dropped. Surrounding segments are NOT renumbered in time; their start/end timings are preserved. |

## Error handling

- `_merge_consecutive_duplicates` on an empty list → returns `[]`. On a single segment → returns it unchanged.
- Translator parsing failure for a SKIP'd segment → no special path needed; SKIP is just a string, and the existing missing-translation retry already handles the case where the LLM gives back something unparseable.
- A SKIP'd segment's source text is preserved on disk in the source SRT (`{id}_zh.srt`); only the translated SRT (`{id}_vi.srt`) drops it. So if the user disables `skip_noise` and re-runs translation, all source segments are still there.

## Testing

### Unit — `tests/test_ocr_dedup.py` (new)

- `test_no_duplicates_passes_through`: 3 distinct-text segments → returned unchanged.
- `test_two_adjacent_dupes_merge_with_spanning_timing`: `[(0,1,"a"), (2,3,"a")]` → `[(0,3,"a")]`.
- `test_three_plus_adjacent_dupes_collapse`: `[(0,1,"a"), (1,2,"a"), (2,3,"a")]` → `[(0,3,"a")]`.
- `test_non_adjacent_dupes_kept_separate`: `[(0,1,"a"), (1,2,"b"), (2,3,"a")]` → unchanged.
- `test_strip_handles_whitespace_differences`: `[(0,1,"a"), (1,2,"a ")]` → merged.
- `test_empty_text_segments_not_merged`: `[(0,1,""), (1,2,"")]` → returned as two separate entries (empty doesn't trigger merge).
- `test_empty_input`: `[]` → `[]`.
- `test_single_segment`: `[(0,1,"a")]` → unchanged.

### Unit — `tests/test_translator_skip.py` (new)

- `test_skip_instruction_appended_when_flag_on`: build a translator with `skip_noise=True`, call `_build_system_prompt`, assert the output contains `__SKIP__`.
- `test_skip_instruction_omitted_when_flag_off`: `skip_noise=False` → prompt does NOT contain `__SKIP__`.
- `test_translate_srt_drops_skip_segments` (async): stub `_call_llm` to return numbered output where two of five lines are `__SKIP__`; assert the output SRT has 3 entries with the right timings preserved.
- `test_skip_marker_substring_in_real_translation_kept`: LLM returns `"this segment is __SKIP__ adjacent"` for a line — exact-match check means it's kept as-is, not dropped.

### Integration — `tests/test_translate_integration.py` (existing if applicable, else new)

One end-to-end test that wires `get_translator(config)` with `translation.skip_noise: true`, runs a small fixture SRT through, asserts the SKIP'd lines are absent from the output.

## Verification

1. `python -m pytest tests/test_ocr_dedup.py tests/test_translator_skip.py -v` → all new tests pass.
2. `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py` → full BE suite green.
3. **Manual smoke (after merge):**
   - Pipeline a Douyin video known to have duplicate-frame OCR captures → check `data/srt/{id}_zh.srt` no longer contains adjacent identical lines.
   - Same video has a visible channel handle / watermark on screen → check the translated SRT (`{id}_vi.srt`) is missing those rows.
   - Set `translation.skip_noise: false` in `config.yaml`, re-translate → noise lines should reappear (proving the gating works).

## Files touched

- `src/transcriber/ocr.py` — add `_merge_consecutive_duplicates` helper (module-level, ~20 lines) + one-line wire-up at the end of `_build_segments_from_frames`.
- `src/translator/llm.py` — `__init__` gains `skip_noise: bool = True`; `_build_system_prompt` conditionally appends the SKIP clause; `translate_srt` filters SKIP entries before reassembly.
- `src/translator/__init__.py` — `get_translator` reads `skip_noise` from config.
- `config/config.example.yaml` — document the flag.
- `tests/test_ocr_dedup.py` — new, 8 unit tests.
- `tests/test_translator_skip.py` — new, 4 unit tests.
- `tests/test_translate_integration.py` — new or extended, 1 integration test.
- `CHANGELOG.md`, `README.md`.

## Out of scope (future ideas)

- Post-translate LLM review pass (already ruled out).
- Configurable SKIP sentinel (e.g. a different marker per profile).
- Per-profile `skip_noise` overrides (today it's a global config knob).
- Surfacing the count of SKIP'd / merged segments to the FE for user awareness.
- Telemetry on how often the SKIP path fires across videos.
