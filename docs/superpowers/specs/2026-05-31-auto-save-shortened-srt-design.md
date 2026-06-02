# Auto-save shortened SRT as a version snapshot

## Goal

After every successful dub generation (full pipeline or DubTab "Generate TTS Audio"), auto-save the post-shortening SRT as a new immutable version snapshot. The user can then pick it from the editor's version dropdown and see what the dub actually said, in the same per-segment timeline they edit on.

## Why

Today, the only SRT in the editor after a pipeline run is the *original* translation. The TTS assembler's Stage 0 (sentence merging) and Stage 1.5 (LLM shortening) rewrite the text the dub speaks; that rewritten text lives only in `sentence_plan` (in memory) and `{wav}.plan.json` (on disk, alongside the WAV). The user can't see it from the editor — they have to dig through the JSON or play the dub and listen.

This closes the loop: every dub leaves behind both the WAV *and* a viewable SRT of what was actually said.

## Non-goals

- Auto-switching the editor to the new version after save. The user picks it from the existing dropdown.
- Auto-pruning old shortened versions. Re-dubbing 10 times = 10 versions; user deletes via the existing VersionPanel.
- Editing the in-memory `sentence_plan` shape, or surfacing per-sentence shortening metadata (e.g., `needs_review`) in the saved SRT. The version is plain SRT text + timings; the JSON plan log stays the source of truth for that.
- Pulling the saved version's text into the dub *re-generation* loop. If the user edits this version and re-dubs from it, the existing version-aware TTS path handles that — no special "re-shorten the shortened" logic.

## Architecture

Both pipeline and manual TTS call `src/tts/runner.py::run_tts_track`, which receives the source `segments` and gets back `sentence_plan` from `assembler.generate_full_track`. That is the single insertion point.

```
run_tts_track
  ├─ … existing dub generation …
  ├─ … existing .plan.json / .plan.tsv write …
  └─ save_shortened_version(           ← NEW
       video_id, language,
       sentence_plan, original_segments,
       dub_label=f"dub: {provider}/{voice}",
     )
         │
         ├─ for each group in sentence_plan:
         │     split_sentence_to_segments(group.text, original[group.segment_indices])
         │
         ├─ reassemble per-segment SRT (original timings, new text)
         │
         └─ versions.import_as_version(video_id, language, srt_bytes, name=dub_label)
                  → writes data/srt/{id}_{lang}.v{N+1}.srt
                  → appends to versions.json
                  → returns VersionEntry
```

## Components

### `src/tts/shortened_srt.py` — new file

Two pure functions, no I/O. Easy to unit-test, easy to reason about.

```python
def split_sentence_to_segments(merged_text: str, original_texts: list[str]) -> list[str]:
    """Distribute a shortened sentence back across its original N segments.

    Proportional by char length of the original texts. Words from
    ``merged_text`` are split at whitespace and allocated to segments in
    order; each segment gets a number of words such that its share of the
    total approximates its original char-length share.

    Edge cases:
      - len(original_texts) == 1 → returns [merged_text] unchanged.
      - merged_text is empty → returns ['', '', …] matching segment count.
      - more segments than words → trailing segments get ''.
    """

def build_shortened_srt(
    sentence_plan: list[dict],
    original_segments: list[dict],
) -> list[dict]:
    """Reassemble a per-segment SRT from sentence_plan + original timings.

    For each entry in sentence_plan, look up the segment_indices, call
    split_sentence_to_segments, and write the resulting text back into a
    list[dict] in the SubtitleSegment shape parse_srt produces.

    Original timings are preserved verbatim. Segments not referenced by
    any plan entry (shouldn't happen for a successful dub but defensive)
    are copied through unchanged.
    """
```

### `src/api/versions.py` — extend

Add one helper that wraps `import_as_version` but takes pre-parsed segments instead of raw SRT bytes:

```python
def import_segments_as_version(
    video_id: str,
    language: str,
    segments: list[dict],
    name: str | None = None,
) -> VersionEntry:
    """Like import_as_version but writes SubtitleSegment dicts directly
    (no parse round-trip). Calls write_srt to produce the file."""
```

This keeps `import_as_version`'s bytes-validation path intact for the upload endpoint while giving the in-process caller a cleaner entry point.

### `src/tts/runner.py` — wire it in

After the existing `.plan.json` / `.plan.tsv` block, in a `try` (so a failure here doesn't fail the dub):

```python
try:
    from src.tts.shortened_srt import build_shortened_srt
    from src.api.versions import import_segments_as_version

    if sentence_plan:
        shortened_segments = build_shortened_srt(sentence_plan, segments)
        entry = import_segments_as_version(
            video_id=video_id,
            language=language,
            segments=shortened_segments,
            name=f"dub: {provider}/{voice}",
        )
        logger.info(f"Saved shortened version {entry.id} as '{entry.name}'")
except Exception as e:  # noqa: BLE001 — version save is convenience, not core
    logger.warning(f"Could not save shortened version: {e}")
```

## Data flow

```
Working draft SRT   →   parse_srt   →   segments (list[dict])
                                              │
                                              ▼
                              assembler.generate_full_track(segments, …)
                                              │
                                              ▼
                       (WAV path, sentence_plan with merged + shortened text)
                                              │
              ┌───────────────────────────────┴────────────────────────────┐
              ▼                                                            ▼
       {wav}.plan.json                                            build_shortened_srt(
       (existing dev log)                                           sentence_plan,
                                                                    original segments
                                                                  )
                                                                          │
                                                                          ▼
                                                           import_segments_as_version
                                                                          │
                                                                          ▼
                                                   data/srt/{id}_{lang}.v{N+1}.srt
                                                   appended to versions.json
                                                   visible in editor dropdown
```

## Behavior

| Scenario | Result |
|---|---|
| Successful dub, some sentences shortened | New `v{N+1}` snapshot, name `dub: {provider}/{voice}` |
| Successful dub, no shortening needed | Still creates a snapshot — its text differs from original only in sentence-merging (concatenated punctuation may differ from per-segment text). Some users find this confirming; no special-case skip. |
| Dub fails before sentence_plan exists | No snapshot. The except-clause in `run_tts_track` swallows it. |
| Snapshot save fails (disk full, race) | Logged, dub still reported successful. The WAV is the primary deliverable. |
| Re-dub same source version with new voice | A second new snapshot is created. No overwrite. |
| Re-dub with the *same* provider+voice+source-version | The dub WAV is overwritten in place (existing behavior); the snapshot is *not* overwritten — a new auto-numbered snapshot is appended. User can delete the stale one. |
| Pipeline run | Auto-snapshot fires from inside `run_tts_track`, same as DubTab. One code path. |

## Error handling

- `build_shortened_srt` returning fewer segments than the original (shouldn't happen, but defensive): the imported version simply has fewer rows. The editor handles that today (a version with 3 rows in a video that originally had 5 just shows 3 rows when previewed).
- `import_segments_as_version` raising on file-write error: caught by the `try` in `run_tts_track`, logged at WARNING, dub completion proceeds.
- Provider/voice with characters that would be ugly in a version name (slashes, spaces): kept verbatim. The version name field is free-text already.

## Testing

### Unit — `tests/test_shortened_srt.py` (new file)

`class TestSplitSentence`:
- `test_single_segment_passthrough` — N=1, returns the input as one element.
- `test_two_segments_proportional` — original `["foo", "bar"]` (3+3 chars) split of "hello world" → `["hello", "world"]`.
- `test_unbalanced_segments` — original `["a", "the quick brown fox"]` (1+19 chars) → first segment gets a small share, second gets the bulk.
- `test_more_segments_than_words` — original `["a", "b", "c"]`, text `"hi"` → `["hi", "", ""]`.
- `test_empty_input` — empty merged_text → `["", "", ""]` for 3 segments.

`class TestBuildShortenedSrt`:
- `test_preserves_original_timings` — feed a 5-segment original and a 2-entry plan that covers segments [0,1,2] and [3,4]; assert output has 5 rows with original `startTime`/`endTime` and redistributed text.
- `test_unshortened_sentence_keeps_text` — plan entry's text == original concat → split returns text close to original.
- `test_segment_not_referenced_by_plan_copies_through` — plan only covers segments [0,1]; segment [2] keeps original text. (Shouldn't happen in practice but defensive.)

### Integration — `tests/test_tts_versioned.py` (existing file, add a class)

`class TestRunTtsTrackAutoSavesShortenedVersion`:
- Monkeypatch `SRT_DIR` to tmp_path; stub the assembler to return a known `sentence_plan`; stub the TTS provider to write a fake WAV; run `run_tts_track`; assert `data/srt/{id}_{lang}.v1.srt` exists and `versions.json` has the new entry with `name == "dub: <provider>/<voice>"`.
- Failure path: stub `build_shortened_srt` to raise; confirm `run_tts_track` still returns the dub result and the failure is logged (no version file written).

## Verification

1. `python -m pytest tests/test_shortened_srt.py tests/test_tts_versioned.py -v` — new tests green.
2. `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py` — full BE suite green.
3. **Manual smoke (after merge):** run pipeline on a short Douyin clip → open the per-video editor → version dropdown shows `Working draft` + `v1 — dub: google/<voice>`. Pick v1 → segment list shows the shortened/merged text with the original timings.

## Files touched

- New: `src/tts/shortened_srt.py` (~80 lines), `tests/test_shortened_srt.py` (~120 lines).
- Modified: `src/api/versions.py` (one new helper, ~15 lines), `src/tts/runner.py` (one new try-block, ~15 lines), `tests/test_tts_versioned.py` (one new class, ~50 lines).
- Docs: `CHANGELOG.md`, `README.md` (Implementation Progress checklist).
