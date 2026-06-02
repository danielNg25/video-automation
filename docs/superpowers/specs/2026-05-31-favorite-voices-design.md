# Favorite voices — quick-select chips

## Goal

Let the user mark TTS voices they like and surface them as a row of clickable chips below the voice dropdown on both the per-video DubTab and the standalone Dub Studio. Picking a favorite is one click; the existing dropdown stays put for everything else.

## Why

Both pages today load the full voice list for the selected (provider, language) every render. Google alone returns ~400 voices; even after the inline filter (`{friendly_name} ({gender})` in the `<select>`) the list is long and the user has to re-find the same handful of voices they actually use across videos. A favorites chip strip shortcuts that without removing the full list.

## Non-goals

- BE storage / cross-device sync. Favorites live in localStorage alongside the existing TTS picker prefs.
- Cross-tab live sync (changes in tab A reflect in tab B without reload). Possible later via the `storage` event but YAGNI for now.
- Per-account, per-project, or shareable favorite lists. One list per browser.
- Reordering chips. Display order matches insertion order; user removes + re-adds to reorder.
- Rich metadata on favorites (notes, tags, ratings). Just a flat list.
- Auto-suggest favorites based on usage frequency. The user marks explicitly.

## Architecture

One pure-helper module + one shared React component, wired into both existing voice pickers.

```
                                    ┌────────────────────────────┐
                                    │   ui-app/src/utils/        │
                                    │   favoriteVoices.ts        │
                                    │                            │
                                    │  loadFavorites()           │
                                    │  saveFavorites(list)       │
                                    │  isFavorite(fav)           │
                                    │  toggleFavorite(fav)       │
                                    │  favoritesFor(prov, lang)  │
                                    │                            │
                                    │  Pure functions over       │
                                    │  localStorage key          │
                                    │  'tts_favorite_voices_v1'  │
                                    └────────────┬───────────────┘
                                                 │
                  ┌──────────────────────────────┴──────────────────────────────┐
                  ▼                                                             ▼
   ┌─────────────────────────┐                              ┌─────────────────────────┐
   │  ui-app/src/components/ │                              │  ui-app/src/components/ │
   │  FavoriteVoiceStrip.tsx │                              │  FavoriteVoiceToggle.tsx│
   │                         │                              │                         │
   │  Props:                 │                              │  Props:                 │
   │   favorites: list       │                              │   provider, voice,      │
   │   voices: VoiceInfo[]   │                              │   language              │
   │   onPick(voiceId)       │                              │   disabled              │
   │   onRemove(fav)         │                              │                         │
   │                         │                              │  Star button; toggles   │
   │  Renders a row of chips │                              │  the favorite via the   │
   │  with hover-× remove    │                              │  helper module.         │
   └──────────┬──────────────┘                              └──────────┬──────────────┘
              │                                                         │
              ▼                                                         ▼
              ┌─────────────────────────────────────────────────────────┐
              │ Used identically in:                                    │
              │  ui-app/src/pages/videoDetail/DubTab.tsx                │
              │  ui-app/src/pages/DubStudio.tsx                         │
              │                                                         │
              │ Strip rendered immediately under the voice <select>     │
              │ Toggle rendered to the right of the voice <select>      │
              └─────────────────────────────────────────────────────────┘
```

## Components

### `ui-app/src/utils/favoriteVoices.ts` — new

Pure functions over a single `localStorage` key. No React, no I/O beyond localStorage.

```ts
export interface FavoriteVoice {
  provider: string;
  voice: string;
  language: string;
}

const STORAGE_KEY = 'tts_favorite_voices_v1';

export function loadFavorites(): FavoriteVoice[];
export function saveFavorites(list: FavoriteVoice[]): void;
export function isFavorite(fav: FavoriteVoice): boolean;
export function toggleFavorite(fav: FavoriteVoice): FavoriteVoice[];
export function favoritesFor(provider: string, language: string): FavoriteVoice[];
```

Behaviour:

- `loadFavorites`: reads + parses JSON; returns `[]` for missing key, parse failure, or non-array values. Filters out entries missing any of the three required fields.
- `saveFavorites`: writes JSON. Caller is responsible for ordering.
- `isFavorite`: true if any entry matches all three fields exactly.
- `toggleFavorite`: if currently a favorite, returns the list with it removed; otherwise returns the list with it appended. Calls `saveFavorites` internally to persist. Returns the new list so callers can update state.
- `favoritesFor`: filter by `(provider, language)` — these are the active scope on either page at any moment.

### `ui-app/src/components/FavoriteVoiceStrip.tsx` — new

```tsx
interface Props {
  favorites: FavoriteVoice[];   // already filtered for the current scope
  voices: VoiceInfo[];          // currently loaded; used to look up friendly_name
  selectedVoiceId: string;      // for highlighting the active chip
  onPick: (voiceId: string) => void;
  onRemove: (fav: FavoriteVoice) => void;
}
```

Renders nothing when `favorites.length === 0`. Otherwise renders a `★ Favorites` label and a `flex-wrap` row of pill chips. Each chip:
- Text: `voices.find(v => v.name === fav.voice)?.friendly_name ?? fav.voice` (graceful fallback if the voice was removed server-side).
- Click on the chip body: calls `onPick(fav.voice)`.
- Hover reveals a × button at the right of the chip; click calls `onRemove(fav)`. The × handler calls `event.stopPropagation()` so the chip's onPick does not also fire.
- The chip matching `selectedVoiceId` gets a `bg-primary/15 text-primary` tint to show "this is what's loaded".

### `ui-app/src/components/FavoriteVoiceToggle.tsx` — new

```tsx
interface Props {
  provider: string;
  voice: string;
  language: string;
  disabled?: boolean;          // disable when no voice selected
  onChange?: () => void;       // optional notify (parent re-loads favorites)
}
```

A `<button>` rendered next to the voice dropdown. Internally calls `loadFavorites` + `isFavorite` to decide its visual state (filled vs outlined star). Click → `toggleFavorite` → fires `onChange` so the parent re-renders the strip.

### Wire-in: DubTab + DubStudio

Both pages already hold `provider`, `language`, `voice` (or `selectedVoiceId`) in state. The wire-up is purely additive:

1. Track `favorites` in the parent component's state (initialised from `loadFavorites()`).
2. Pass `favoritesFor(provider, language)` filtered list down to `<FavoriteVoiceStrip>`.
3. Render `<FavoriteVoiceToggle>` immediately after the voice `<select>` (same flex row).
4. Render `<FavoriteVoiceStrip>` immediately below the voice `<select>` row.
5. The `onChange` callback on the toggle and the `onRemove` on the strip both re-call `loadFavorites()` and update parent state, so the strip refreshes in real time.

## Data flow

```
User clicks ★ on the toggle for (google, vi-VN-Wavenet-A, vi)
  → toggleFavorite()  ← writes to localStorage
  → onChange()        ← parent re-loads favorites
  → re-render
  → <FavoriteVoiceStrip> now includes the new chip

User clicks the new chip in the strip
  → onPick("vi-VN-Wavenet-A")
  → parent's existing onChangeSelectedVoiceId (same code path as <select> onChange)
  → dropdown updates, persisted to localStorage as the current pick

User hovers a chip and clicks ×
  → onRemove(fav)
  → toggleFavorite()  ← removes from localStorage
  → parent re-loads favorites
  → chip disappears
```

## Behavior

| Scenario | Result |
|---|---|
| Strip with 0 favorites for current (provider, language) | Strip not rendered at all (no empty header). |
| User picks a voice via the strip | Same effect as picking it from the dropdown — the dropdown reflects the new selection. |
| User starts the page with a stale favorite (voice was removed server-side) | Chip renders with the bare voice id (no friendly name). Click still attempts to pick; dropdown will show the voice id in its options if present, "no voice available" otherwise. User can hover-× to remove. |
| Two tabs open, user adds a favorite in tab A | Tab B does not update live. Visible after reload. Documented; YAGNI for live sync. |
| Star button when no voice selected (`selectedVoiceId === ""`) | Button is disabled. |
| User favorites the same voice twice | `toggleFavorite` removes on the second click — no duplicates in the list. |
| Switching provider or language | The strip re-filters to the new scope; previously-shown chips disappear if they don't match. |

## Error handling

- `loadFavorites` returning `[]` on malformed JSON is the recovery path. No user-visible error.
- `saveFavorites` failing (e.g. localStorage quota exceeded — very unlikely with a flat array of small strings) is caught and logged at WARNING via `console.warn`; the in-memory state still updates so the user sees the change for the session. The next reload would revert. Acceptable for a non-critical preference.

## Testing

### Unit — `ui-app/src/utils/__tests__/favoriteVoices.test.ts` (new)

vitest. Mock localStorage via the jsdom env (already in the existing test-setup).

- `test_loadFavorites_returns_empty_when_key_missing`
- `test_loadFavorites_returns_empty_on_malformed_json`
- `test_loadFavorites_filters_entries_missing_required_fields`
- `test_isFavorite_matches_all_three_fields_exactly`
- `test_toggleFavorite_adds_when_absent`
- `test_toggleFavorite_removes_when_present`
- `test_favoritesFor_filters_by_provider_and_language`

### Component — `ui-app/src/components/__tests__/FavoriteVoiceStrip.test.tsx` (new)

- `test_renders_nothing_with_empty_favorites`
- `test_renders_chip_per_favorite_with_friendly_name_fallback`
- `test_click_chip_fires_onPick_with_voice_id`
- `test_remove_button_fires_onRemove_with_full_favorite`
- `test_chip_matching_selected_voice_gets_highlight_class`

### Component — `ui-app/src/components/__tests__/FavoriteVoiceToggle.test.tsx` (new)

- `test_renders_outlined_star_when_not_favorited`
- `test_renders_filled_star_when_favorited`
- `test_click_toggles_localStorage_and_fires_onChange`
- `test_disabled_when_voice_empty`

### Integration — DubStudio + DubTab existing test files

One additional test in each existing test file confirms the strip is rendered when favorites exist for the current scope. Avoids re-asserting the strip's internals (already covered by the component test).

## Verification

1. `cd ui-app && npx vitest run` — full FE suite passes, +14 tests.
2. `cd ui-app && npx tsc --noEmit` — clean.
3. **Manual smoke:**
   - Open DubStudio, pick a voice, click the star → chip appears below.
   - Pick a different voice; click that chip → dropdown jumps back to the first voice.
   - Hover the chip, click ×; chip disappears.
   - Switch the language to one with no favorites; strip hides.
   - Open a per-video editor's DubTab; the same favorites are visible (shared list).

## Files touched

- New: `ui-app/src/utils/favoriteVoices.ts` (~50 lines).
- New: `ui-app/src/utils/__tests__/favoriteVoices.test.ts` (~80 lines).
- New: `ui-app/src/components/FavoriteVoiceStrip.tsx` (~50 lines).
- New: `ui-app/src/components/__tests__/FavoriteVoiceStrip.test.tsx` (~70 lines).
- New: `ui-app/src/components/FavoriteVoiceToggle.tsx` (~30 lines).
- New: `ui-app/src/components/__tests__/FavoriteVoiceToggle.test.tsx` (~60 lines).
- Modified: `ui-app/src/pages/DubStudio.tsx` — add favorites state + render strip + render toggle (~15 lines net).
- Modified: `ui-app/src/pages/videoDetail/DubTab.tsx` — same (~15 lines net).
- Modified: `ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx` — one new test.
- Modified: `ui-app/src/pages/__tests__/DubStudio.test.tsx` — one new test.
- Docs: `CHANGELOG.md` and `README.md`.

## Out of scope (future ideas, not in this PR)

- Cross-tab live sync via `storage` events.
- Drag-to-reorder chips.
- Importing/exporting favorites as JSON.
- BE storage for cross-device sync.
- Showing favorite counts or last-used timestamps on chips.
