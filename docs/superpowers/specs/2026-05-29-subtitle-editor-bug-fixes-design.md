# Subtitle Editor Bug Fixes (focused, no layout redesign)

> **Sub-project 1 of 3** in the dub-sync rebuild. Sub-project 2 (subtitle versioning + dub-version picker) and sub-project 3 (standalone text→voice tool) get their own specs and PRs after this lands.

## Goal

Make the subtitle editor's time inputs actually typable and make the "add subtitle" action discoverable. No row-layout redesign — the current visual is fine; only the broken interactions and the hover-hidden add button need fixing.

## Problem

`ui-app/src/components/editor/SegmentList.tsx` has two interaction bugs and one discoverability bug:

1. **Time inputs fight focus.** Each `<input>` for `startTime` / `endTime` has `onClick={() => onSeek(...)}` ([SegmentList.tsx:103](ui-app/src/components/editor/SegmentList.tsx#L103)). Clicking the input to type seeks the video, which re-renders the player and steals focus from the input. The user reports they cannot type into the timer at all.
2. **Silent format rejection.** The inputs are uncontrolled (`defaultValue=`) and only commit on blur via `handleTimestampBlur`, which silently returns when `isValidSrtTimestamp(value)` is false ([SegmentList.tsx:54](ui-app/src/components/editor/SegmentList.tsx#L54)). A wrong-format value (e.g. typed `8:00` instead of `00:00:08,000`) is discarded with no feedback; the value reverts.
3. **Add button hover-only.** The action toolbar (`✂` `⏍` `+` `×`) is wrapped in `opacity-0 group-hover:opacity-100` ([SegmentList.tsx:114](ui-app/src/components/editor/SegmentList.tsx#L114)). The "Add subtitle after" button only appears when the mouse hovers the row. Users report not knowing the button exists. There's also no way to add to the end of an empty list.

The textarea has the same `onClick={() => onSeek(startSec)}` issue ([SegmentList.tsx:154](ui-app/src/components/editor/SegmentList.tsx#L154)) — clicking to position the text caret jumps the video.

## Non-goals

- No row layout redesign (kept compact / monospace as today).
- No ±100ms nudge buttons, no snap-to-playhead buttons, no inline mini-timeline. The user explicitly rejected these.
- No subtitle versioning, no dub-sync changes — those are sub-project 2.
- No global keyboard shortcuts (J/L scrub, etc.) in this PR. Esc/Enter inside a focused time input are standard form behavior and are in scope.

## Architecture

The change is confined to one file, `ui-app/src/components/editor/SegmentList.tsx`, plus its first vitest file. No backend, no API, no schema changes. The component already receives `onUpdate`, `onAdd`, `onDelete`, `onSplit`, `onMerge`, `onSeek` callbacks — we wire them up correctly and stop calling `onSeek` from elements meant for text/time editing.

## The four fixes

### Fix 1 — Stop seeking from edit surfaces

Remove `onClick={() => onSeek(...)}` from:
- the `startTime` input ([SegmentList.tsx:103](ui-app/src/components/editor/SegmentList.tsx#L103))
- the `endTime` input (no current onClick, but ensure none is added)
- the textarea ([SegmentList.tsx:154](ui-app/src/components/editor/SegmentList.tsx#L154))

Seek remains available on the `#index` label ([SegmentList.tsx:92-98](ui-app/src/components/editor/SegmentList.tsx#L92-L98)) — that element is purely a jump affordance. Update its `title` from `"Jump to segment"` to `"Click to jump video to this segment"` so the affordance reads even before hover.

### Fix 2 — Controlled time inputs with inline error indicator

Convert each time input to controlled (`value=` + `onChange=`):

- Local state per input holds the in-progress string (uncommitted typing).
- On every keystroke, `isValidSrtTimestamp` is checked; if invalid, the input gets a red border (using the same red token the existing delete button uses — `text-red-400` is the project convention; pick a matching border class like `border-red-400/60`) and a `title` attribute reading `"Format: HH:MM:SS,mmm"`.
- On `blur` (or `Enter` keydown), if valid, the commit path runs:
  - parse via `srtTimestampToSeconds`
  - enforce `start < end` (kept from current `handleTimestampBlur`)
  - call `onUpdate(i, { ...seg, [field]: value })`
- On blur with an invalid value, the local state reverts to the segment's current value (matches current behavior) but the red border clears.
- Pressing `Esc` while focused also reverts to the segment's current value (extra: lets the user back out of a mid-edit).

### Fix 3 — Always-visible actions on the active row

Replace the single hover-based opacity wrapper ([SegmentList.tsx:114](ui-app/src/components/editor/SegmentList.tsx#L114)) with a class condition:

- `isActive` → `opacity-100` (always shown)
- otherwise → keep `opacity-0 group-hover:opacity-100` (unchanged for inactive rows)

The inactive-row behavior is intentional: a long subtitle list stays calm visually, only the row you're currently working on shows its toolbar. Tooltips are unchanged.

### Fix 4 — Sticky "Add subtitle" button at list end

Add a single full-width button after the last segment in the list:

- Label: `+ Add subtitle`
- Disabled when there is no video duration loaded yet.
- Clicking calls `onAdd(segments.length - 1)` — same `onAdd` callback, last-index path. EditorTab's existing [`handleAddSegment`](ui-app/src/pages/videoDetail/EditorTab.tsx#L251) handles the non-empty case correctly (when `afterIndex === segments.length - 1`, it computes `newStart = afterEnd + 0.1`, `newEnd = afterEnd + 2`).
- **EditorTab patch required for empty list:** when `segments.length === 0`, the bottom button calls `onAdd(-1)` and the current `handleAddSegment` would crash on `prev[-1].endTime`. Add a guard: when `afterIndex < 0`, insert a row at `start = 0`, `end = min(2, videoDuration)`. Same callback signature, no new endpoint.
- Button styling matches the existing `mock-button` aesthetic (dashed primary border, transparent background) — see the focused-fix.html mockup for the exact look.

This button is purely additive — the per-row `+` button stays.

## Component data flow

Before:
```
seg.startTime ──(defaultValue)──> <input> ──blur──> handleTimestampBlur ──> onUpdate
                                  click ──> onSeek (BUG — fights focus)
```

After:
```
seg.startTime ──(initial)──> local state ──> <input value=>
local state ──onChange──> validate ──> set border color
local state ──onBlur/Enter──> validate + start<end ──> onUpdate
local state ──onEsc──> reset to seg.startTime
```

No global state. The component already owns its local state for the active-row detection; adding two `useState` strings per input is trivial.

## Tests

New vitest file at `ui-app/src/components/editor/__tests__/SegmentList.test.tsx` covering:

1. **time input is typable** — render with one segment, focus the start input, fire `change` events for each character of `"00:00:05,000"`, expect input value to equal that string (no reverts mid-type, no `onSeek` calls). Confirms Fix 1.
2. **invalid format shows error class but does not call onUpdate** — type `"abc"`, fire `blur`, expect `onUpdate` not called and the input value reverts to `seg.startTime`. Confirms Fix 2 silent-reject fix.
3. **valid format on blur calls onUpdate** — type `"00:00:07,000"` over `"00:00:05,000"`, fire `blur`, expect `onUpdate` called once with `{...seg, startTime: "00:00:07,000"}`.
4. **start ≥ end rejects on blur** — type a start time ≥ current end, fire `blur`, expect `onUpdate` not called.
5. **clicking the # index label seeks** — confirms Fix 1's seek-only-via-index design.
6. **active row shows toolbar without hover** — set the active index via the `currentTime` prop, render, expect the `+ Add after` button to be reachable by `getByTitle("Add segment after")` without firing a `mouseenter` event.
7. **bottom "+ Add subtitle" button calls onAdd with last index** — render with 3 segments, click the bottom button, expect `onAdd(2)` called.
8. **bottom button on empty list** — render with `segments: []`, click the bottom button, expect `onAdd(-1)` called.

Tests use `@testing-library/react` + `vitest`. The vitest config already exists at `ui-app/vitest.config.ts` (added in PR #15). No new dev deps.

No backend test changes (this is an FE-only fix).

## Verification

- `cd ui-app && npm run test src/components/editor/__tests__/SegmentList.test.tsx` — all 8 new tests pass.
- `cd ui-app && npm run lint` — clean.
- Manual smoke (after merge): open the video editor for any video with existing subtitles.
  - Click into the start-time input, type a new HH:MM:SS,mmm value, blur → segment updates, video does not jump while typing.
  - Type garbage → red border appears live, blur reverts, no toast/error spam.
  - Click an inactive row → it becomes active, action icons appear without hover.
  - Click the bottom `+ Add subtitle` button → a new row appears at the end with sensible timestamps.
  - Click the `#` number on any row → video seeks to that segment's start (preserved behavior).

## Out of scope (covered by later sub-projects)

- **Subtitle versioning** — saving as a named version, dub tab dropdown to pick which version to dub. Sub-project 2.
- **Standalone text → voice tool** — paste arbitrary text, pick voice, download WAV. Sub-project 3.
- **Undo/redo, keyboard shortcuts, drag-to-reorder, find-and-replace** — none of these are in the user's stated scope. Skipped.

## Critical files

- [ui-app/src/components/editor/SegmentList.tsx](ui-app/src/components/editor/SegmentList.tsx) — fixes 1-4 land here
- [ui-app/src/utils/srtTime.ts](ui-app/src/utils/srtTime.ts) — referenced for `isValidSrtTimestamp` and conversion helpers (reused as-is)
- [ui-app/src/pages/videoDetail/EditorTab.tsx](ui-app/src/pages/videoDetail/EditorTab.tsx) — review (and patch if needed) the `addSegment` handler's behavior for `onAdd(-1)` / `onAdd(segments.length - 1)` empty-list case
- `ui-app/src/components/editor/__tests__/SegmentList.test.tsx` — new vitest file
- [CHANGELOG.md](CHANGELOG.md) — `Fixed` entry under `[Unreleased]`
- [README.md](README.md) — progress section entry
