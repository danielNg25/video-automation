# UI App Overhaul — Design

**Status:** Approved 2026-05-22
**Branch:** continuation of `feature/phase4-dubbing-redesign-spec`
**Goal:** Remove dead pages, consolidate two subtitle editors, restructure VideoDetail and Settings so each page does one thing clearly.

## Motivation

The UI grew organically across phases and accumulated:

- A `/upload` nav item with no route (dead link).
- A Dashboard page the user no longer wants — its only valuable surface (pipeline-run history) lives near the wrong primary action.
- Two subtitle editors: the standalone `/editor/:videoId` page (611 lines) and an embedded `SubtitleEditorPanel` (592 lines) inside VideoDetail. Both use the same primitives. The standalone page is orphaned — nothing in the app links to it.
- A 995-line VideoDetail that bolts the entire pipeline (transcribe, translate, dub, export) onto one accordion-style page, plus a redundant copy of the subtitle editor.
- A 760-line Settings page with 7 inline sections, a sub-nav that scrolls to anchors, and three places that duplicate the TTS playback-speed / underlay-dB controls.
- A `mockData.ts` file most of whose exports are no longer consumed.

This overhaul removes the dead surfaces, picks one editor, and gives the remaining pages a clear job each.

## Scope

In scope:

1. Information-architecture cleanup (nav + routes).
2. Pipeline page (`/`) gains the Recent Runs section migrated from Dashboard.
3. VideoDetail (`/videos/:id`) rebuilt as a tabbed page.
4. Settings (`/settings`) rebuilt with a two-level sidebar.
5. TTS settings sync model — one source of truth in Settings, per-job overrides preserved.
6. Dead-code removal.

Out of scope:

- Translation Profiles page (`/profiles`) — left as-is.
- Video Studio grid (`/videos`) — left as-is.
- Subtitle editor primitives in `ui-app/src/components/editor/` — left as-is.
- API / backend changes — none planned. This is a UI-only restructure. All existing API endpoints stay.

## Section 1 — Information Architecture

### Sidebar nav (final)

| Item | Route | Source |
|---|---|---|
| Pipeline | `/` | existing `DownloadTranscribe.tsx` mounted at root |
| Video Studio | `/videos` | unchanged |
| Translation Profiles | `/profiles` | unchanged |
| Settings | `/settings` | restructured |

Four items. Dropped: `Dashboard` and `Upload`.

### Routes

| Route | Component | Change |
|---|---|---|
| `/` | `DownloadTranscribe` | **moved from `/download` to `/`** |
| `/download` | `DownloadTranscribe` | redirect to `/` (one release of grace) |
| `/videos` | `VideoList` | unchanged |
| `/videos/:videoId` | `VideoDetail` | rebuilt (Section 3) |
| `/editor/:videoId` | `SubtitleEditor` | unchanged; now actively linked from VideoDetail |
| `/profiles` | `TranslationProfiles` | unchanged |
| `/settings` | `Settings` | rebuilt (Section 4) |
| ~~Dashboard `/`~~ | — | **removed** |

### Files to remove

- `ui-app/src/pages/Dashboard.tsx` (416 lines)
- `ui-app/src/components/SubtitleEditorPanel.tsx` (592 lines) — its primitives in `components/editor/` stay
- `ui-app/src/components/SubtitleReplacement.tsx` — only if no remaining references found at execution time (verify before deleting)
- From `ui-app/src/data/mockData.ts`: `srtSegments`, `recentDownloads`, `pipelineRows`, `activityFeed`, `platformAuths`, `platformOptions`, `fontOptions`, `languageOptions`, `settingsSections`. Keep only `navItems` (and the `NavItem` interface).

### `mockData.ts` after cleanup

```ts
export interface NavItem {
  readonly icon: string;
  readonly label: string;
  readonly path: string;
}

export const navItems: readonly NavItem[] = [
  { icon: 'rocket_launch', label: 'Pipeline', path: '/' },
  { icon: 'movie_edit', label: 'Video Studio', path: '/videos' },
  { icon: 'translate', label: 'Translation Profiles', path: '/profiles' },
  { icon: 'settings', label: 'Settings', path: '/settings' },
];
```

## Section 2 — Pipeline page (`/`) — add Recent Runs

The existing Pipeline form (URL input, platform picker, Advanced drawer, save-as-default, in-progress stage tracker) stays unchanged. **Add** a new section below it.

### Layout addition

```
┌─────────────────────────────────────────────────┐
│ [ existing pipeline form ]                      │
│ [ existing PipelineStageTracker when running ]  │
├─────────────────────────────────────────────────┤
│ Recent Runs                  [All|Running|✓|✗]  │
│ ┌───────────────────────────────────────────┐   │
│ │ ▸ video_title.mp4 · done · tiktok,yt · 3m │   │
│ │ ▸ Batch · 5 videos · 4 done, 1 failed     │   │
│ │ ▸ ...                                     │   │
│ └───────────────────────────────────────────┘   │
│ Showing 10 of N · auto-refresh every 30s        │
└─────────────────────────────────────────────────┘
```

### Behavior

- Section title: "Recent Runs"
- Filter tabs identical to today's Dashboard: All / Running / Completed / Failed
- Show up to 10 most recent runs (today's Dashboard shows 20 — we trim by half to avoid bloating the Pipeline page)
- Each row expandable (clicking opens child-video list, errors, URL list)
- Per-row actions: **View** (single-video runs → navigates to `/videos/:id`), **Retry** (only for `status === 'failed'`)
- Polling: `setInterval(refresh, 30_000)` matching today's Dashboard
- Falls back to the legacy `/api/pipeline/history` endpoint if `/api/pipeline/runs` returns empty, exactly as today's Dashboard does

### Code organization

Extract the run-fetching + state into `ui-app/src/lib/usePipelineRuns.ts`:

```ts
export interface PipelineRun { /* same shape as Dashboard's PipelineRun */ }

export function usePipelineRuns(refreshIntervalMs = 30_000): {
  runs: PipelineRun[];
  refresh: () => Promise<void>;
};
```

The Recent Runs section is a new component `ui-app/src/components/PipelineRunsTable.tsx` consuming `usePipelineRuns()`. Lives inside `DownloadTranscribe.tsx`. Pure presentational + a few callbacks.

The stats cards (Total Videos / Processed Today / Active Tasks) and the Recent Activity feed from Dashboard are **dropped** — vanity metrics in the first case, redundant data in the second.

## Section 3 — VideoDetail (`/videos/:videoId`) — tabbed layout

### Shell

```
┌─────────────────────────────────────────────────────┐
│ ← Back · Video Detail                  [edit title] │
├─────────────────────────────────────────────────────┤
│ [ Overview ] [ Translate ] [ Dub ] [ Export ]       │
├─────────────────────────────────────────────────────┤
│                                                     │
│                  <active tab body>                  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

- Tab state in URL query: `?tab=overview|translate|dub|export` (defaults to `overview`)
- Refresh + share preserve the active tab
- Tab transitions: no animation needed; instant content swap

### Files

```
ui-app/src/pages/VideoDetail.tsx                 (shell only, ~120 lines)
ui-app/src/pages/videoDetail/OverviewTab.tsx     (~150 lines)
ui-app/src/pages/videoDetail/TranslateTab.tsx    (~180 lines)
ui-app/src/pages/videoDetail/DubTab.tsx          (~250 lines)
ui-app/src/pages/videoDetail/ExportTab.tsx       (~120 lines)
```

Net: ~820 lines split across 5 files instead of one 995-line file.

### Tab — Overview

- Title (editable inline, same `patchVideoTitle` flow as today)
- Thumbnail (small)
- Metadata grid: resolution, codec, size, duration, video_id
- Status badge: Downloaded / Transcribed / Translated / Exported (same color logic)
- **Open Editor** button (primary, only if `has_srt`) → navigates to `/editor/:videoId`
- **Re-extract subtitles** button (secondary, only if `has_srt`)
- **Extract subtitles** big primary button + spinner (if `!has_srt`)
- Transcription progress card (when `isTranscribing`)
- Download original MP4 button (icon-only in the corner)
- Error banner (top of page, dismissible)
- Completed stages chip row: `Downloaded → Transcribed → Translated → Exported` with current state highlighted

### Tab — Translate

- Translation profile picker (`getProfiles()`)
- Target language picker (`vi`, `en`)
- LLM backend picker (anthropic / deepseek / openai)
- Model picker (depends on backend)
- API key input (browser localStorage, never sent to server config)
- Base URL input (for OpenAI-compatible providers)
- **Use defaults from Settings** info row at top — "LLM defaults loaded from Settings. Edits here apply only to this run."
- Run button — calls existing `postTranslate` endpoint
- Progress bar
- Existing translation list with re-translate per language

### Tab — Dub

- TTS provider picker (`getTTSProviders()`)
- Voice profile picker (`getTTSProfiles()`)
- Voice ID input (with provider voice-library link)
- TTS API key input (browser localStorage)
- Language picker (TTS target language)
- Playback speed slider (pre-filled from `tts_playback_speed` localStorage default)
- Underlay-dB slider (pre-filled from `tts_underlay_db` localStorage default)
- **Use direct voice** toggle
- **Save as default** button — writes current speed + underlay back to localStorage
- Generate button — calls existing `postTTS`
- Progress bar
- Existing TTS audio list with play / preview / delete (same `TTSPreview` component)

### Tab — Export

- Platform multi-select (TikTok / YouTube / Facebook / X) — same `PLATFORM_INFO` map
- Export button — triggers full-pipeline call with `force=true` for selected platforms
- Progress bar (via SSE / polling same as today)
- Existing exports list — per-platform, each row has Download MP4 + View-in-modal
- The "View modal" is the same modal pattern from VideoList today

### What's no longer in VideoDetail

- ❌ Embedded `SubtitleEditorPanel` (deleted; replaced by the **Open Editor** button)
- ❌ Inline export controls hidden inside the editor panel (now lives in the Export tab)

## Section 4 — Settings (`/settings`) — two-level sidebar

### Shell

```
┌──────────────────────────────────────────────────────┐
│ Settings                                             │
├─────────────────┬────────────────────────────────────┤
│ SOURCES         │                                    │
│   Douyin API    │                                    │
│   API Keys      │                                    │
│                 │  <selected category's form>        │
│ PROCESSING      │                                    │
│   Subtitles     │                                    │
│   Translation   │                                    │
│   Dubbing       │                                    │
│   Export & Video│                                    │
│                 │                                    │
│ SYSTEM          │                                    │
│   Pipeline      │                                    │
│                 │  ┌─────────────────────────────┐   │
│                 │  │ [Cancel]      [Save] (sticky)│   │
│                 │  └─────────────────────────────┘   │
└─────────────────┴────────────────────────────────────┘
```

- URL deep-link: `/settings?category=ocr` (replaces today's `#hash` pattern). Categories: `douyin`, `apikeys`, `ocr`, `translation`, `tts`, `video`, `pipeline`.
- Default category: `douyin`
- Right pane shows only the active category's form — no infinite scroll. Each category mounts independently.
- Sticky **Save** footer in the right pane — save is per-category and explicit (not auto-save).
- Loading + saved-confirmation states already exist; keep them.

### Files

```
ui-app/src/pages/Settings.tsx                          (shell + sidebar, ~120 lines)
ui-app/src/pages/settings/DouyinSection.tsx            (~120 lines)
ui-app/src/pages/settings/ApiKeysSection.tsx           (~100 lines)
ui-app/src/pages/settings/OcrSection.tsx               (~140 lines)
ui-app/src/pages/settings/TranslationSection.tsx       (~110 lines)  [NEW]
ui-app/src/pages/settings/TtsSection.tsx               (~120 lines)
ui-app/src/pages/settings/VideoExportSection.tsx       (~90 lines)
ui-app/src/pages/settings/PipelineSection.tsx          (~80 lines)
```

Net: 1 shell + 7 category files instead of one 760-line monolith.

### Category contents

**SOURCES → Douyin API** — Cookie status (loaded / expired / never set), Cookie textarea + Save + Test buttons, test-result feedback. Same `getCookieStatus / putCookie / testCookie` calls.

**SOURCES → API Keys** — Per-provider keys (Anthropic / DeepSeek / OpenAI / ElevenLabs / Google / OpenAI TTS). localStorage-only via `loadApiKeys / saveApiKey`. Help text: "Stored in browser only, never sent to server config."

**PROCESSING → Subtitles (OCR)** — fps, confidence threshold, similarity threshold, subtitle region min_y, watermark max-frequency, crop-bottom-pct. Same `getConfig / putConfig` flow, same dropdown options.

**PROCESSING → Translation** — Global LLM defaults: backend, model, API key, base URL. localStorage via `loadLLMPrefs / saveLLMPrefs`. Link to `/profiles` for managing translation style profiles. **NEW category** — these defaults previously had no Settings home and leaked into VideoDetail.

**PROCESSING → Dubbing (TTS)** — Default provider, default voice IDs per provider, default language, default playback speed slider, default underlay-dB slider. localStorage. The contract: these are the **defaults** other surfaces pre-fill from.

**PROCESSING → Export & Video** — ffmpeg CRF, preset, audio bitrate. `getConfig / putConfig`.

**SYSTEM → Pipeline** — data_dir, max_concurrent, retry_attempts, retry_delay, skip_existing. `getConfig / putConfig`.

## Section 5 — TTS settings sync model

### Single source of truth

Settings → Dubbing (TTS) holds the canonical defaults via these localStorage keys (already in use today):

```
tts_playback_speed       : number (1.0 – 2.0)
tts_underlay_db          : number (-24 – 0)
tts_selected_provider    : string (provider id)
tts_voice_id_<provider>  : string (per-provider voice id)
tts_language             : string
```

### Per-job override pattern

Pipeline page (Advanced drawer) and VideoDetail Dub tab follow this contract:

1. **On mount:** read each key from localStorage; use the value as initial state. Use the same `Number.isFinite` + range-clamp defaults the code already uses.
2. **Edits:** purely local component state. Never auto-write back.
3. **Save as default button:** explicit user action. Writes current values back to localStorage. Toast/badge confirms "Saved as default".

Both surfaces continue to call the existing POST endpoints with whatever values are currently in component state — independent of whether they match the saved defaults.

### Why not Settings-only

Per-video tuning is genuinely useful (e.g., a fast speaker needs a slower playback). Removing per-job overrides would force a bounce to Settings and back. Per-job overrides + an opt-in "Save as default" preserves both clean defaults and flexible per-job tuning.

## Cross-cutting

### Loading + suspense

All new pages use the same lazy-loaded pattern from `App.tsx`. Suspense fallback unchanged.

### Polling + state

The existing `PipelineStatusProvider` (from the previous spec) continues to own the running-pipeline status. Recent Runs uses its own `usePipelineRuns()` hook — independent concern.

### Persistence

No new server-side state. All UI-state additions (active tab in URL, selected category in URL) are URL-driven so refresh and share work.

### Browser support

Same React 19 + TypeScript 5 + Tailwind 4 stack. No new dependencies.

## Risks

- **Removing `Dashboard` deep-links from any future surface** — none today (verified via grep). The Recent Runs UX is equivalent for retry / view actions.
- **Removing `SubtitleEditorPanel`** — verify no other consumer at execution time (e.g., a deep-link or tour that might reference it). Today the only consumer is `VideoDetail.tsx`.
- **Tab-state URL change** — VideoDetail today uses `openPanels` state that doesn't survive refresh. Moving to `?tab=` is a strict improvement; no migration needed.
- **Settings URL change** — today the page uses `#hash` for category. The new `?category=` is a different shape. Any external bookmarks would break; acceptable since the app has no external links to settings sub-sections.

## Migration order (execution-time decisions live in the plan)

Each step must leave the app fully usable. The sequencing below is chosen so we never delete a surface before its replacement exists.

1. **Add `usePipelineRuns` hook + `PipelineRunsTable` component** — pure additions, no deletions. Imported nowhere yet.
2. **Mount Recent Runs on the Pipeline page** — now the run history exists in its new home.
3. **Reroute `/` to `DownloadTranscribe`; add `/download` → `/` redirect** — Dashboard.tsx temporarily orphaned but still on disk.
4. **Delete `Dashboard.tsx` + its imports + the unused `mockData.ts` exports + the `Upload` and `Dashboard` nav items.** Safe now: nothing references the page; the run history lives on Pipeline.
5. **VideoDetail tabbed redesign** — biggest refactor; split into shell + 4 tab components. Delete `SubtitleEditorPanel.tsx` only after VideoDetail no longer imports it.
6. **Settings two-level redesign** — split into shell + 7 category files. Migrate URL hash to `?category=` query param.
7. **TTS sync alignment** — add "Save as default" button to VideoDetail Dub tab; verify pre-fill contract across Pipeline Advanced + Dub tab.
8. **Final pass** — sweep README checklist + CHANGELOG, push branch, offer PR.
