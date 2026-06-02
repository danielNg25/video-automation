# Favorite voices — quick-select chips with custom nicknames

## Goal

Let the user mark TTS voices they like and surface them as a row of clickable chips below the voice dropdown on both the per-video DubTab and the standalone Dub Studio. Picking a favorite is one click. Each chip can optionally carry a user-defined nickname (e.g. "Sarah - news voice") so the strip reads as a personal shortlist rather than a wall of voice IDs.

## Why

Both pages today load the full voice list for the selected (provider, language) every render. Google alone returns ~400 voices; even after the inline filter (`{friendly_name} ({gender})` in the `<select>`) the list is long and the user has to re-find the same handful of voices they actually use across videos. A favorites chip strip shortcuts that without removing the full list.

## Non-goals

- BE storage / cross-device sync. Favorites live in localStorage alongside the existing TTS picker prefs.
- Cross-tab live sync (changes in tab A reflect in tab B without reload). Possible later via the `storage` event but YAGNI for now.
- Per-account, per-project, or shareable favorite lists. One list per browser.
- Reordering chips. Display order matches insertion order; user removes + re-adds to reorder.
- Rich metadata beyond a single-line nickname (multi-line notes, tags, ratings). Just `nickname` for now.
- Asking for a nickname at star time. The star button is a one-click action; nickname is set later via the pencil icon. Two code paths for the same field is unnecessary complexity.
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

Stored shape: one localStorage key shared by both pages.

```ts
// localStorage['tts_favorite_voices_v1']
[
  { provider: "google", voice: "vi-VN-Wavenet-A", language: "vi", nickname: "Sarah" },
  { provider: "elevenlabs", voice: "abc123...", language: "vi" },
  { provider: "google", voice: "en-US-Wavenet-D", language: "en", nickname: "news anchor" }
]
```

Identity (for dedup, isFavorite, remove, rename) is the `(provider, voice, language)` tuple. `nickname` is optional metadata.

```ts
export interface FavoriteVoice {
  provider: string;
  voice: string;
  language: string;
  nickname?: string;   // user-defined display label; missing/empty → fall back to friendly_name/voice id
}

const STORAGE_KEY = 'tts_favorite_voices_v1';

export function loadFavorites(): FavoriteVoice[];
export function saveFavorites(list: FavoriteVoice[]): void;
export function isFavorite(fav: Pick<FavoriteVoice, 'provider' | 'voice' | 'language'>): boolean;
export function toggleFavorite(fav: FavoriteVoice): FavoriteVoice[];
export function renameFavorite(
  fav: Pick<FavoriteVoice, 'provider' | 'voice' | 'language'>,
  nickname: string,
): FavoriteVoice[];
export function favoritesFor(provider: string, language: string): FavoriteVoice[];
```

Behaviour:

- `loadFavorites`: reads + parses JSON; returns `[]` for missing key, parse failure, or non-array values. Filters out entries missing any of the three required identity fields (`provider`, `voice`, `language`). Missing/non-string `nickname` is normalised to `undefined`.
- `saveFavorites`: writes JSON. Caller is responsible for ordering.
- `isFavorite`: true if any entry's `(provider, voice, language)` matches exactly. Ignores nickname.
- `toggleFavorite`: identity-based dedup. If a matching entry exists, returns the list with it removed (drops the existing nickname too — re-adding starts fresh, which is the intuitive "I unstarred it, then re-starred it" behaviour). Otherwise appends with the supplied nickname (often empty when called from the star toggle). Calls `saveFavorites` internally. Returns the new list.
- `renameFavorite`: finds the entry by identity and updates its `nickname`. An empty/whitespace-only nickname is stored as `undefined` (so the chip falls back to the friendly name). No-op if no matching entry. Calls `saveFavorites`. Returns the new list.
- `favoritesFor`: filter by `(provider, language)` — the active scope on either page at any moment.

### `ui-app/src/components/FavoriteVoiceStrip.tsx` — new

```tsx
interface Props {
  favorites: FavoriteVoice[];   // already filtered for the current scope
  voices: VoiceInfo[];          // currently loaded; used to look up friendly_name
  selectedVoiceId: string;      // for highlighting the active chip
  onPick: (voiceId: string) => void;
  onRemove: (fav: FavoriteVoice) => void;
  onRename: (fav: FavoriteVoice, nickname: string) => void;
}
```

Renders nothing when `favorites.length === 0`. Otherwise renders a `★ Favorites` label and a `flex-wrap` row of pill chips. Each chip:

- **Text**: precedence is `fav.nickname` (if truthy) → `voices.find(v => v.name === fav.voice)?.friendly_name` → `fav.voice` (bare id). Graceful three-step fallback so a chip always renders something.
- **Title (tooltip)**: always shows the full identity `"{provider} · {voice}"` so the user can see what's behind a nickname.
- **Click on the chip body**: calls `onPick(fav.voice)`.
- **Hover reveals two icon buttons** at the right of the chip:
  - ✎ (pencil) → opens a `window.prompt('Nickname (leave blank to clear)', fav.nickname ?? '')`. On commit, calls `onRename(fav, value.trim())`. On cancel (null), no-op.
  - × → calls `onRemove(fav)`.
  - Both handlers call `event.stopPropagation()` so the chip's onPick does not also fire.
- **Selected highlight**: the chip matching `selectedVoiceId` gets a `bg-primary/15 text-primary` tint to show "this is what's loaded".

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
5. The `onChange` callback on the toggle, the `onRemove`, and the `onRename` callbacks on the strip all re-call `loadFavorites()` and update parent state, so the strip refreshes in real time.

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

User hovers a chip and clicks ✎
  → window.prompt('Nickname (leave blank to clear)', currentNickname)
  → user types 'Sarah' + OK
  → onRename(fav, 'Sarah')
  → renameFavorite()  ← updates the entry's nickname in localStorage
  → parent re-loads favorites
  → chip re-renders with 'Sarah' as its label
```

## Behavior

| Scenario | Result |
|---|---|
| Strip with 0 favorites for current (provider, language) | Strip not rendered at all (no empty header). |
| User picks a voice via the strip | Same effect as picking it from the dropdown — the dropdown reflects the new selection. |
| User starts the page with a stale favorite (voice was removed server-side) | Chip renders with the nickname if set, otherwise the bare voice id (no friendly name available). Click still attempts to pick; dropdown will show the voice id in its options if present, "no voice available" otherwise. User can hover-× to remove. |
| Two tabs open, user adds a favorite in tab A | Tab B does not update live. Visible after reload. Documented; YAGNI for live sync. |
| Star button when no voice selected (`selectedVoiceId === ""`) | Button is disabled. |
| User favorites the same voice twice | `toggleFavorite` removes on the second click — no duplicates in the list. The nickname (if any) is lost on the remove half; re-adding starts with no nickname. |
| Switching provider or language | The strip re-filters to the new scope; previously-shown chips disappear if they don't match. |
| User opens the rename prompt and clicks Cancel | No-op (`window.prompt` returns null on cancel). Existing nickname untouched. |
| User opens the rename prompt and submits an empty/whitespace string | Nickname is cleared (stored as `undefined`); chip falls back to the friendly name or voice id. |
| User renames a favorite with a very long string | Stored as-is; the chip's CSS truncates the visible text (`max-w-[160px] truncate`) with the full nickname accessible via the tooltip. |

## Error handling

- `loadFavorites` returning `[]` on malformed JSON is the recovery path. No user-visible error.
- `saveFavorites` failing (e.g. localStorage quota exceeded — very unlikely with a flat array of small strings) is caught and logged at WARNING via `console.warn`; the in-memory state still updates so the user sees the change for the session. The next reload would revert. Acceptable for a non-critical preference.

## Testing

### Unit — `ui-app/src/utils/__tests__/favoriteVoices.test.ts` (new)

vitest. Mock localStorage via the jsdom env (already in the existing test-setup).

- `test_loadFavorites_returns_empty_when_key_missing`
- `test_loadFavorites_returns_empty_on_malformed_json`
- `test_loadFavorites_filters_entries_missing_required_fields`
- `test_loadFavorites_normalises_invalid_nickname_to_undefined`
- `test_isFavorite_matches_identity_only_ignoring_nickname`
- `test_toggleFavorite_adds_when_absent`
- `test_toggleFavorite_removes_when_present`
- `test_toggleFavorite_drops_nickname_on_remove`
- `test_renameFavorite_updates_existing_entry`
- `test_renameFavorite_clears_nickname_when_blank`
- `test_renameFavorite_noop_when_entry_missing`
- `test_favoritesFor_filters_by_provider_and_language`

### Component — `ui-app/src/components/__tests__/FavoriteVoiceStrip.test.tsx` (new)

- `test_renders_nothing_with_empty_favorites`
- `test_renders_chip_with_nickname_when_set`
- `test_renders_chip_with_friendly_name_when_no_nickname`
- `test_renders_chip_with_voice_id_when_no_nickname_and_no_friendly_name`
- `test_click_chip_fires_onPick_with_voice_id`
- `test_remove_button_fires_onRemove_with_full_favorite`
- `test_remove_button_does_not_fire_onPick`
- `test_rename_button_opens_prompt_and_fires_onRename_with_trimmed_value`
- `test_rename_button_cancel_is_noop`
- `test_chip_matching_selected_voice_gets_highlight_class`

### Component — `ui-app/src/components/__tests__/FavoriteVoiceToggle.test.tsx` (new)

- `test_renders_outlined_star_when_not_favorited`
- `test_renders_filled_star_when_favorited`
- `test_click_toggles_localStorage_and_fires_onChange`
- `test_disabled_when_voice_empty`

### Integration — DubStudio + DubTab existing test files

One additional test in each existing test file confirms the strip is rendered when favorites exist for the current scope. Avoids re-asserting the strip's internals (already covered by the component test).

## Verification

1. `cd ui-app && npx vitest run` — full FE suite passes, +26 tests (12 helper + 10 strip + 4 toggle).
2. `cd ui-app && npx tsc --noEmit` — clean.
3. **Manual smoke:**
   - Open DubStudio, pick a voice, click the star → chip appears below with the friendly name.
   - Hover the chip, click ✎; in the prompt, type "Sarah" and OK → chip relabels to "Sarah". Tooltip still shows the full identity.
   - Hover and click ✎ again, submit empty → chip falls back to the friendly name.
   - Pick a different voice; click the original chip → dropdown jumps back, chip gets the highlight tint.
   - Hover the chip, click ×; chip disappears.
   - Switch the language to one with no favorites; strip hides.
   - Open a per-video editor's DubTab; the same favorites (with nicknames) are visible (shared list).

## Files touched

- New: `ui-app/src/utils/favoriteVoices.ts` (~65 lines — gains `renameFavorite` and the nickname normaliser).
- New: `ui-app/src/utils/__tests__/favoriteVoices.test.ts` (~110 lines — 12 tests).
- New: `ui-app/src/components/FavoriteVoiceStrip.tsx` (~70 lines — gains the pencil button + prompt handling).
- New: `ui-app/src/components/__tests__/FavoriteVoiceStrip.test.tsx` (~100 lines — 10 tests).
- New: `ui-app/src/components/FavoriteVoiceToggle.tsx` (~30 lines).
- New: `ui-app/src/components/__tests__/FavoriteVoiceToggle.test.tsx` (~60 lines — 4 tests).
- Modified: `ui-app/src/pages/DubStudio.tsx` — favorites state + render strip + render toggle (~15 lines net).
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
