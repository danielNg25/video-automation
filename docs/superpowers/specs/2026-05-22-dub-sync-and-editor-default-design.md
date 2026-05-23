# Dub-Sync + Editor-as-Default-View — Design

**Status:** Approved 2026-05-22
**Branch:** new feature branch (TBD at planning time — likely `feature/dub-sync`)
**Builds on:** `feature/phase4-dubbing-redesign-spec` (the UI app overhaul that ships first via its own PR)
**Goal:** Make the subtitle editor the default per-video workspace, and add a "Sync Dub" feature that regenerates only the changed segments after a sub edit.

## Motivation

Two related shifts in the per-video workflow:

1. **Subtitle editing is the primary action on a video.** After the pipeline runs, the most common manual operation is correcting subtitles. Landing on an Overview tab and then clicking "Open Editor" adds a wasted hop. The editor should be the default view.

2. **The dub goes stale when subs are edited.** Today, editing `{video_id}_{lang}.dubsync.srt` updates the burn-in caption but leaves the spoken audio frozen at the pre-edit text — drift accumulates silently. Users have to manually re-run the entire dub stage (~50 TTS API calls, ~30-60s, full cost) to fix one typo. The right model: edit text → click "Sync Dub" → only the changed segments get re-synthesised.

## Scope

In scope:

1. **Part A — UX restructure** (small): VideoDetail tabs reshuffled so Editor is default, Overview removed.
2. **Part B — Dub-sync feature** (real): per-segment cache + change detection + partial re-synth + targeted "Sync Dub" trigger.

Out of scope:

- Timing-edit-triggered dub re-sync (planner's drift math changes; complex; defer)
- Segment add/delete-triggered partial sync (forces full regen anyway; not optimised this round)
- Multi-language dub re-sync in parallel (one language at a time)
- Style-edit triggers (style is burn-in only, doesn't affect dub — explicitly NOT a sync trigger)
- Auto-sync on save / debounce / exit-editor (we picked explicit button)

## Part A — UX restructure

### Current state (post UI-overhaul, commit `70fc49f`)

```
/                  →  Pipeline launcher (DownloadTranscribe)
/videos            →  Video Studio grid
/videos/:videoId   →  VideoDetail with 4 tabs: Overview / Translate / Dub / Export
                      Default tab = Overview
                      Overview shows: video info card + "Open Editor" button → navigates to /editor/:id
/editor/:videoId   →  Standalone subtitle editor (canonical)
```

### Target state

```
/                  →  unchanged
/videos            →  unchanged
/videos/:videoId   →  VideoDetail with 4 tabs: Editor / Translate / Dub / Export
                      Default tab = Editor
                      Editor tab mounts the existing subtitle-editor primitives inline
/editor/:videoId   →  REMOVED. The route disappears. The standalone page disappears.
```

### Architectural changes

- The standalone `ui-app/src/pages/SubtitleEditor.tsx` page (611 lines) is **deleted**.
- A new `ui-app/src/pages/videoDetail/EditorTab.tsx` is created. It contains the same JSX + state + behaviour as the standalone page, but as a tab component (zero-prop, fits the existing VideoDetail tabs pattern).
- The existing `OverviewTab.tsx` is **deleted**.
- `VideoDetail.tsx`'s tab array changes: `(['overview', 'translate', 'dub', 'export'])` → `(['editor', 'translate', 'dub', 'export'])`.
- Default `activeTab` flips from `'overview'` to `'editor'`.
- The `Tab` type union updates accordingly.
- `App.tsx`'s `/editor/:videoId` route is removed (and its `SubtitleEditor` lazy import).
- VideoList's "Open Studio" button continues to navigate to `/videos/:videoId` — same URL, but it now lands in the Editor tab.

### Language picker default

The Editor tab's language picker should default to whichever language has a `dubsync.srt` on disk (preferring `vi` over `en` when both exist). If no dubsync exists yet, fall back to the first non-Chinese SRT language. This makes dubsync the explicit default, not just "what happens because `_resolve_srt_path` happens to pick it."

The picker still lets users switch to other languages — including `zh` (original Chinese) for read-only inspection.

### Behaviour preservation

- All editor functionality (timeline drag, segment add/delete, style panel, preview burn-in, save) works identically inside the Editor tab.
- The `?tab=editor` query param replaces the disappearing `/editor/:id` route. Direct deep-links to specific videos still work.
- The "Re-extract subtitles" button (previously on Overview tab) moves into the Editor tab header — it makes more sense next to the segments it would re-extract.
- Save status indicators (saved / unsaved changes / save failed) continue to render in the editor toolbar.

### Why not full /videos/:id → /editor/:id redirect?

We considered redirecting `/videos/:id` straight to a standalone editor route, but that leaves Translate / Dub / Export with no obvious home. Keeping the tabs (Editor as default) preserves the recently-built tab architecture and the discoverability of per-stage re-runs.

### Tradeoff acknowledged

Phase 2 of the UI overhaul (Tasks 5–8) explicitly picked the full-screen `/editor/:id` page over the embedded `SubtitleEditorPanel` for the editor experience, because subtitle editing benefits from screen real estate. This spec walks part of that back — the editor becomes a tab again, which means it shares vertical space with the page chrome (tab bar + TopBar). Net loss of ~50px of vertical height for the editor.

The tradeoff is justified by the workflow win: editing is the default action; users no longer click "Open Editor" every time. If the squeeze proves painful in practice, a future iteration could add a "fullscreen" toggle on the tab itself that hides the tab bar.

## Part B — Dub-sync feature

### Trigger model

- User edits subtitles in the Editor tab.
- On save, server compares each segment's text in the new SRT vs the existing `{video_id}_{lang}.dubsync.srt`.
- If **any** segment's text differs → persist `dub_out_of_sync: true` in `data/logs/{video_id}_state.json`.
- Editor renders a yellow banner near the toolbar: "Dub is out of sync with current subtitles. [Sync Dub]"
- User clicks **Sync Dub** → server runs the sync flow.
- While syncing: progress bar (existing SSE pattern from TTS generation).
- On complete: banner disappears; dub clip + dubsync.srt updated; success toast for 2s.

### Detection logic (server-side)

```python
# Pseudocode for the per-save check in src/api/routers/editor.py
def _check_dub_sync(video_id: str, language: str, new_segments: list[Segment]) -> bool:
    dubsync_path = Path(f"data/srt/{video_id}_{language}.dubsync.srt")
    if not dubsync_path.exists():
        return False  # No dub generated yet — nothing to sync against
    old_segments = parse_srt(dubsync_path)
    if len(old_segments) != len(new_segments):
        return True  # Segment count changed → structural; flag as out-of-sync (forces full regen on Sync Dub click)
    for old, new in zip(old_segments, new_segments):
        if _clean_text(old.text) != _clean_text(new.text):
            return True
    return False
```

The text comparison uses the same `_clean_text` (from `src/tts/base.py`) that the assembler uses, so trivial whitespace differences don't trigger false positives.

### Sync flow (server-side)

The new endpoint `POST /api/videos/{id}/dub/sync` accepts `{language: str}` and returns `{task_id}`. The task runs:

1. **Load saved metadata** (`data/tts/{video_id}/dub_meta_{lang}.json`):
   - `provider`, `voice_id`, `language`
   - `playback_speed`, `underlay_db`
   - Per-segment metadata: original timing + previous text (for comparison)
   - Created on first dub generation; updated on each sync.

2. **Compute dirty segments**: compare current SRT text vs saved metadata's previous text per segment index.

3. **If segment count differs OR > 50% of segments are dirty** → fall back to full dub regen (existing `src/tts/runner.py` flow). The 50% heuristic prevents pathological "re-sync 80 of 100 segments individually" cases.

4. **Else, partial sync**:
   - Load cached natural-speed WAVs for unchanged segments from `data/tts/{video_id}/segments/{lang}_{idx:03d}.wav`.
   - Re-synth each dirty segment at natural speed using saved provider/voice/lang.
   - Save the new natural-speed clip to the cache (overwriting the old).
   - Run `Planner.build_plan(...)` with the NEW per-segment texts and ORIGINAL per-segment timings. This is the existing pure function — no changes needed.
   - Stage 3 (the assembler's batched shortening re-synth) runs if the planner flags new shortenings — re-uses existing logic.
   - Assemble final WAV: concatenate clips at planner-determined positions + apply atempo + mix underlay (existing `_concatenate_with_silence` + ffmpeg paths).
   - Write new `{video_id}_{lang}.dubsync.srt`.
   - Update `dub_meta_{lang}.json` with new per-segment texts.
   - Clear `dub_out_of_sync` in `state.json`.

5. **SSE progress events** at each stage boundary (synth-changed-segments / planning / re-assemble), matching the existing dub pipeline's event shape.

### Per-segment WAV cache

**New persistent state** under `data/tts/{video_id}/`:

```
segments/
  {lang}_001.wav    # natural-speed clip for segment index 1
  {lang}_002.wav
  ...
dub_meta_{lang}.json  # metadata + per-segment texts
```

**When populated:**
- First full dub generation in `src/tts/assembler.py`: after the per-segment synth pass, copy each clip into the segments/ directory before atempo/concatenation modifies it. This is an O(segment_count) file copy — negligible cost relative to the TTS calls.

**Size estimate:** A 60-second video with ~20 segments at 24kHz mono PCM is ~1-2 MB per language. Sub-MB per natural-speed clip. Storage cost is bounded and acceptable.

**Cleanup:**
- Delete the per-video `data/tts/{video_id}/` tree when the video itself is deleted (extend the existing `deleteVideo` API in `src/api/routers/videos.py`).
- Otherwise persistent — survives across pipeline runs, allows re-sync indefinitely.

**Cache invalidation:**
- A dub regenerated from scratch (full TTS stage, not sync) overwrites the entire cache for that language. Re-sync after that uses the new cache.
- If the user changes provider/voice/playback_speed/underlay AND clicks Sync Dub, the saved metadata mismatches; the server falls back to full regen (so the new parameters take effect everywhere).

### API additions

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/videos/{id}/dub/sync` | `{language: str}` | `{task_id}` + SSE stream |
| `GET` | `/api/videos/{id}/dub/status` | — | `{out_of_sync: bool, language: str, last_synced_at: str}[]` (one entry per language with a dub) |

The existing `GET /api/videos/{id}` response gains a `dub_status` field (array of the same shape) so the editor can render the banner without an extra request.

### UI additions

**In `EditorTab.tsx`** (new file, replacing the deleted standalone `SubtitleEditor.tsx`):

- Right above the segment list / timeline, a banner: yellow background, "Dub for {language} is out of sync with current subtitles." + a primary "Sync Dub" button.
- Banner only renders when `dub_status.find(d => d.language === activeLang)?.out_of_sync === true`.
- While syncing: button shows "Syncing… {pct}%" with a spinner.
- On success: banner replaced with "Dub synced." in green for 2 seconds, then hidden.
- On failure: banner replaced with red "Sync failed: {error}" + a Retry button.

No per-segment "dirty" indicator in the segment list this round — keep it simple. The banner is the only signal.

## Risks

- **Cache drift:** if the provider's TTS output changes between when a clip was cached and when sync runs (e.g., ElevenLabs voice model retrained), un-edited segments will sound different from edited ones. Mitigation: log provider+voice+lang in metadata; if the saved values mismatch the current generation request, force full regen.
- **Concurrency:** two browsers editing the same video simultaneously could both flag out_of_sync and trigger overlapping syncs. Acceptable for now (single-user app) — defer locking.
- **Atempo idempotency:** re-applying atempo to a cached clip is fine because we cache the *natural-speed* clip; atempo is recomputed from the planner each sync.
- **Dubsync.srt timing rewrites:** the new dubsync may shift segments by milliseconds relative to old (planner re-runs); existing burn-in subtitle frames will need re-render. Acceptable — the user will re-export anyway.
- **First-time cache population:** any dub generated BEFORE this feature ships has no cache. Sync attempts on those dubs fall through to full regen. Add a banner clarifying "First sync runs the full dub; subsequent syncs are fast."

## Testing strategy

Realistic given the project's testing patterns (backend has unit tests + selective integration tests; UI is mostly manual smoke-test):

- **Unit tests (backend)**: `_check_dub_sync` — segments-count change returns True, text change returns True, whitespace-only change returns False, no dubsync.srt yet returns False. Mock filesystem only.
- **Unit test (backend)**: cache-clip loader — missing clip path returns None / falls back to re-synth; present clip path returns clip bytes.
- **Integration test (backend, slow)**: full sync flow on a fixture video using mocked TTS provider — edit one segment text, assert: only the dirty segment got a TTS call, the cached clips are reused, dubsync.srt is updated, dub_out_of_sync is cleared.
- **Manual QA (UI)**: 1-segment edit → click Sync Dub → verify audio updates ONLY for that segment span; multi-segment edit → same; segment count change → confirm full regen banner / longer progress; provider/voice mismatch → confirm full regen.

## Implementation phasing

The plan will sequence the work so the editor changes and dub-sync feature can land independently (each as a usable commit), with Part A first:

1. **Phase A** — UX restructure: delete OverviewTab + standalone SubtitleEditor page; create EditorTab; rewire VideoDetail tab order. ~1-2 tasks.
2. **Phase B** — Backend dub-sync infrastructure: per-segment cache + metadata + `_check_dub_sync` + the `/dub/sync` endpoint. Unit-tested in isolation. ~3-4 tasks.
3. **Phase C** — Editor wiring: banner UI + Sync Dub button + SSE wiring + dub_status field on GET video. ~1-2 tasks.
4. **Phase D** — Manual QA + finalize.

Each commit leaves the app usable. After Phase A, the editor is the default view but no sync exists. After Phase B, the backend is sync-capable but no UI. After Phase C, the feature is complete.
