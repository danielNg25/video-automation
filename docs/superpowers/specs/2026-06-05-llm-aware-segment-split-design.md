# LLM-aware per-segment split for shortened dubs

**Date:** 2026-06-05
**Status:** Draft

## Goal

When the dub assembler merges several source segments into a single sentence for shortening, the shortened text is currently re-split across those segments by character proportion. That allocator doesn't respect Vietnamese phrase boundaries — a clause-joining conjunction like `mà` ends up dangling at the end of one segment with the conclusion stranded on the next.

Change the LLM shortening call so the LLM itself decides where to split. It already understands Vietnamese clauses; just give it the segment boundaries in the prompt and require boundary-respecting per-segment output.

Cost-neutral: one LLM call already happens, we just change its input and output format.

## Non-goals

- Reworking the planner. Sentence grouping (`segment_indices`) is unchanged.
- Re-synthesising per segment. TTS still synthesises the full merged sentence as one clip so prosody flows naturally across clause boundaries.
- Per-segment shortening when the planner did not merge. Single-segment sentences keep today's flat prompt/format.

---

## Architecture

The change is layered so each step has a single concern:

| Layer | File | Change |
|---|---|---|
| Translator | `src/translator/llm.py` | `shorten_texts_batch` accepts optional `originals: list[str]` per item; prompt switches to hierarchical `N.M` format only when `len(originals) > 1`; parser groups `N.M` lines per sentence; returns `list[list[str]]`. |
| Planner data type | `src/tts/planner.py` | `SentencePlan` gains `target_segment_texts: list[str] | None`. |
| Assembler | `src/tts/assembler.py` | Builds each batch item with `originals` from the source segments; after the LLM call, stores `target_segment_texts` on each `SentencePlan`. Re-synth still uses the merged `target_text` (the concatenation of the per-segment texts). |
| SRT writer | `src/tts/shortened_srt.py` | `build_shortened_srt` prefers `sentence_plan_entry['target_segment_texts']`; falls back to `split_sentence_to_segments` (today's proportional code) when the field is `None` or its length doesn't match. |

### LLM prompt — multi-segment item

For a sentence with N originals (N ≥ 2), the user prompt shows the boundaries:

```
1. [3.2s→2.4s, 1.5x] (2 segments)
   1.1: Chỉ để có một chỗ ngủ trong thành phố,
   1.2: mà cả đời chẳng ngủ ngon được.
```

System-prompt addendum (appended to the existing shortening instructions):

> When a numbered item shows multiple sub-segments (e.g. "1.1, 1.2, ..."), keep that exact structure in your reply. Return one line per sub-segment as "N.M shortened text". Each sub-segment must end at a natural clause boundary in the target language — do not break in the middle of a clause or leave a conjunction dangling at the end of a line. The concatenation of all N.M lines is the shortened sentence.

### LLM prompt — single-segment item

Unchanged from today:

```
1. [3.2s→2.4s, 1.5x] Original text here
```

The parser accepts both shapes; per-item shape is implicit in `originals` length and the prompt only renders the hierarchical block for items with `len(originals) > 1`.

### Output parsing

`_parse_shortening_response` evolves into `_parse_per_segment_response(response, item_segment_counts: list[int]) -> list[list[str]]`:

- Scan lines, classify each as flat (`^(\d+)[\.\)]\s+(.+)$`) or hierarchical (`^(\d+)\.(\d+)[\.\)]?\s+(.+)$`).
- For each item index `i`, collect: the hierarchical `i.M` lines (sorted by `M`), OR a single flat `i.` line. Never both for the same `i` (defensive: if both appear, prefer hierarchical).
- Return `list[list[str]]` where each inner list has length `item_segment_counts[i]` on success.
- On count mismatch for item `i`: return `[]` (empty list) as that item's entry — the caller treats empty as "fall back to proportional".

### Translator return shape

`shorten_texts_batch(items)` returns `list[list[str]]` (one per input item). Per item:

- **Success:** length matches `len(item['originals'])`. Each string is the shortened text for that source segment in order.
- **Failure / over-shortening reject / mismatch:** `[]` — caller treats as fallback.
- **Backward-compat:** items that omit `originals` (or pass `originals=[]`) are treated as length-1 — the parser accepts a flat numbered line and returns `[shortened]`.

The over-shortening floor check (lines 703–719 in `llm.py`) applies to the **concatenated** per-segment text vs the original merged text — same threshold logic as today.

### Assembler

`_run_stage3_shortening` builds each batch item with:

```python
batch.append({
    "text": sp.original_text,
    "originals": [segments[i]["text"] for i in sp.segment_indices],
    "target_pct": int(sp.shorten_pct * 100),
    "current_duration": slot.clip_duration,
    "target_duration": sp.final_duration,
    "speed_ratio": ...,
})
```

After the call, for each `sp, parts in zip(targets, results)`:

- If `parts` is non-empty: `sp.target_segment_texts = parts`; `sp.target_text = " ".join(parts).strip()` (the merged text, used for re-synth and the existing per-sentence text fields).
- If `parts` is empty: leave `sp.target_segment_texts = None` and treat as today (use the merged shortening fallback if the LLM returned a flat single-string for the same item, otherwise mark `needs_review`).

### `SentencePlan`

```python
@dataclass
class SentencePlan:
    ...
    target_segment_texts: list[str] | None = None
```

The planner itself never sets this; it's populated by the assembler post-shortening.

### `build_shortened_srt`

```python
for entry in sentence_plan:
    indices = entry["segment_indices"]
    text = entry["text"]
    per_segment = entry.get("target_segment_texts")
    if per_segment is not None and len(per_segment) == len(indices):
        parts = per_segment
    else:
        parts = split_sentence_to_segments(text, [output[i]["text"] for i in indices])
    for i, part in zip(indices, parts):
        output[i]["text"] = part
```

The runner stuffs `target_segment_texts` into the sentence-plan dicts it writes; reads see the new field.

---

## Behaviour table

| Input shape | LLM returns | Result |
|---|---|---|
| Multi-seg sentence | Hierarchical `N.M` lines, count matches | Per-segment split lands as-is on segments. |
| Multi-seg sentence | Hierarchical `N.M` lines, wrong count | That sentence falls back to proportional split (today's path). Other sentences in the same batch use the LLM split if their counts matched. |
| Multi-seg sentence | Flat `N.` line | That sentence treats the flat line as the merged shortening and falls back to proportional split. |
| Single-seg sentence | Flat `N.` line | Returns `[shortened]`. Unchanged from today. |
| Single-seg sentence | Hierarchical `N.1` line | Accepted as a single segment. Unchanged behavior end-to-end. |
| Whole call fails | — | All items return `[]`. Today's per-item fallback (mark `needs_review`, use original) kicks in. |

---

## Test plan

### `tests/test_translator_shortening.py` (extend)

1. `test_parse_flat_only_today_shape` — flat numbered response, all single-seg items, returns `[[shortened]]` per item.
2. `test_parse_hierarchical_two_segments` — 2-seg item with `1.1` + `1.2` lines, returns `[["...", "..."]]`.
3. `test_parse_hierarchical_three_segments` — 3-seg item with `1.1` + `1.2` + `1.3` lines.
4. `test_parse_count_mismatch_returns_empty_for_that_item` — 3-seg item but only `1.1` + `1.2` present → that item's result is `[]`; other items unaffected.
5. `test_parse_mixed_batch` — item 1 single-seg flat, item 2 multi-seg hierarchical, both succeed in one response.
6. `test_prompt_renders_hierarchical_only_when_multi_seg` — internal helper: verify the rendered user prompt has bullet lines for items with `len(originals) > 1` and a flat line for single-seg items.
7. `test_over_shortening_floor_applies_to_concatenation` — LLM returns per-segment text whose concatenation is below the 40% floor → rejected, returns `[]` for that item.

### `tests/test_shortened_srt.py` (extend)

8. `test_build_uses_target_segment_texts_when_present` — sentence plan entry has `target_segment_texts=['a', 'b']`, indices=`[2, 3]` → output rows 2 and 3 get `'a'` and `'b'` verbatim, allocator NOT called.
9. `test_build_falls_back_when_target_segment_texts_missing` — entry has no `target_segment_texts` → today's behavior.
10. `test_build_falls_back_when_count_mismatch` — entry has `target_segment_texts=['a', 'b']` but `segment_indices=[2, 3, 4]` → falls back to proportional split for that entry.

### `tests/test_tts_assembler.py` (extend or add)

11. `test_stage3_builds_batch_with_originals` — mock the translator; assert each batch item passed to `shorten_texts_batch` includes an `originals` list matching the source segments by index.
12. `test_stage3_populates_target_segment_texts_on_success` — translator returns `[["A", "B"]]` for a 2-seg sentence → `SentencePlan.target_segment_texts == ["A", "B"]` and `target_text == "A B"`.
13. `test_stage3_leaves_target_segment_texts_none_on_fallback` — translator returns `[[]]` → `target_segment_texts is None` and shortening falls through to today's path.

---

## Manual smoke (post-merge)

1. Pick a video where the user reported the bug (sentence merged across two original segments).
2. Run the pipeline. Check `data/srt/{id}_{lang}.dubsync.srt` (or the auto-saved "dub: {provider}/{voice}" version snapshot) — the segment that previously ended with a dangling conjunction (`mà`, `nhưng`, `vì`, etc.) should now end at a natural clause boundary.
3. Open the editor, switch the version picker to the dub snapshot — each row's text should read naturally on its own.
4. Force a malformed LLM response by temporarily setting `target_pct` impossibly low (or by stubbing the translator). The dub should still complete; the dubsync SRT falls back to proportional split silently.

---

## Risks

- **Prompt confusion:** the LLM may occasionally return per-segment text whose concatenation differs in wording from a clean merged shortening. The over-shortening floor check applies to the concatenation, so wildly drifting responses still get rejected per item. Acceptable.
- **Latency:** prompt is slightly longer (extra lines per multi-seg sentence). No new round-trip. Token impact: ~+30 tokens per multi-seg sentence, negligible.
- **`SentencePlan` is a planner type:** adding a field to a planner type might feel like leakage from the assembler. Justified because the field is metadata about how the sentence was rendered, not about the plan itself — and `sentence_plan` dicts (which the runner writes) already carry assembler-populated fields like `target_text`. Same shape.
- **Editor snapshot semantics:** the dubsync snapshot's per-segment text now reflects the LLM's preferred boundaries rather than the original character distribution. Users who relied on the old behavior may notice — but the old behavior IS the bug, so this is the intended change.

---

## Out of scope

- Phase C drift-cap rebalance (the existing module-level known limitation).
- Falling back to proportional split when the LLM is unavailable (`self._translator is None`) — today's `mark needs_review` flow already handles that.
- Reformatting the planner's sentence grouping to avoid merges in the first place — that's a much larger redesign and the user explicitly didn't pick option C.
