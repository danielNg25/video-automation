# TTS Providers Cleanup + Pipeline Launcher Voice Override

**Status:** Draft — ready for implementation planning
**Date:** 2026-05-21
**Scope:** `src/tts/`, `src/api/routers/tts.py`, `config/tts_voices.yaml`, `ui-app/src/pages/DownloadTranscribe.tsx`, `ui-app/src/pages/VideoDetail.tsx`, `pyproject.toml`, `tests/test_tts.py`

## Problem

Two related issues surfaced from auditing the TTS pipeline after the dubbing redesign:

1. **Edge TTS is unreliable.** A real run showed ~40% per-sentence synthesis failures (`NoAudioReceived` from edge-tts) because Microsoft's free service silently drops requests under load. The new failure-fallback (Chinese audio at 0 dB) masks the symptom but Vietnamese dub quality suffers when half the sentences fall back. gTTS and Piper share the same quality/reliability ceiling — gTTS is unofficial Google Translate scraping, Piper is on-device with weaker prosody.

2. **Pipeline launcher silently strips voice overrides for Google/OpenAI.** [ui-app/src/pages/DownloadTranscribe.tsx:221](../../ui-app/src/pages/DownloadTranscribe.tsx#L221):

   ```ts
   const ttsVoiceId = (ttsProviderName === 'elevenlabs' ? (storageGet('tts_voice_id') || '') : '');
   ```

   Only ElevenLabs gets the voice override. For Google, the runner falls back to `voice_profile["voice"]` which today is `vi-VN-HoaiMyNeural` (Edge format) — Google rejects this with "Voice not found". The Video Studio TTS panel does NOT have this bug; only the pipeline launcher.

The user has decided to commit to paid TTS providers for quality, removing the free unreliable ones from the codebase entirely. This spec covers both the cleanup and the pipeline-launcher fix in one pass since they're tightly coupled (removing Edge means migrating all default voice profiles, which interacts with the pipeline launcher's voice override).

## Goals

In priority order:

1. **Reliability.** Eliminate the path that produced 40% per-sentence failure rates in production. Every TTS request goes to a paid provider with an SLA.
2. **Fix the pipeline launcher.** Allow the full pipeline (DownloadTranscribe page) to use Google or OpenAI end-to-end without the voice-name mismatch crash. Mirror the Video Studio TTS panel's per-provider UI.
3. **Reduce surface area.** Three fewer provider modules, three fewer dependencies, three fewer dropdown entries. Less code to maintain.
4. **No breaking changes to existing user state.** Profile names stay the same (text inside the profiles changes). The "API Keys" Settings section is unchanged. Saved `tts_playback_speed` / `tts_underlay_db` localStorage keys are unchanged.
5. **Validate stale voice IDs in localStorage.** Anyone with a saved Edge voice name will hit a provider mismatch after the migration. Clear the saved voice ID when it doesn't match the current provider's voice list.

## Non-goals

- Adding retry-with-backoff to any provider. Paid providers don't need it; free providers are removed.
- Adding new ElevenLabs preset profiles. ElevenLabs voice IDs are personal/account-specific — no useful default to ship.
- Changing the assembler, planner, or runner. Those are unchanged.
- Adding a provider fallback chain (e.g. Google → OpenAI on failure). Out of scope; revisit if paid providers turn out to be unreliable, which is unlikely.

## Provider matrix

| Provider | Status | Reason |
|---|---|---|
| `edge` | **DELETE** | ~40% real-world failure rate. Free, no SLA. |
| `gtts` | **DELETE** | Unofficial Google Translate scraping. Brittle. |
| `piper` | **DELETE** | On-device, lower quality, never used in production. |
| `google` | **KEEP** — new default | Best price/quality ratio. Dedicated Vietnamese Wavenet voices. |
| `elevenlabs` | **KEEP** | Highest quality. Subscription pricing for heavy use. |
| `openai` | **KEEP** | Solid quality, OpenAI ecosystem integration. |

## Changes

### Backend deletions

- Delete `src/tts/edge.py`.
- Delete `src/tts/gtts_provider.py`.
- Delete `src/tts/piper_tts.py`.
- Remove the `if provider_name == "edge":`, `elif "gtts":`, `elif "piper":` branches from `src/tts/__init__.py::get_tts_provider`.
- Change factory fallback default from `"edge"` to `"google"` (line 27).
- Remove `edge-tts>=6.1.0` from `pyproject.toml` `dependencies`.
- Remove the `piper = ["piper-tts>=1.2.0"]` optional dependency from `pyproject.toml` `[project.optional-dependencies]`.
- (`gtts` may not appear as a dependency — verify and remove if present.)
- Remove the three deleted providers from `src/api/routers/tts.py::list_providers` (lines 76-78).

### Voice profile migration (`config/tts_voices.yaml`)

Replace the existing `profiles:` block with the migrated versions. Names stay the same EXCEPT the two with "edge" in the name, which get renamed to remove the misleading suffix.

```yaml
default_provider: google

profiles:
  female-vi-natural:
    provider: google
    voice: "vi-VN-Wavenet-A"
    language: vi
    speed: "+0%"
    pitch: "+0Hz"
  male-vi-natural:
    provider: google
    voice: "vi-VN-Wavenet-B"
    language: vi
    speed: "+0%"
    pitch: "+0Hz"
  female-en-natural:        # renamed from female-en-edge
    provider: google
    voice: "en-US-Wavenet-C"
    language: en
    speed: "+0%"
    pitch: "+0Hz"
  male-en-natural:          # renamed from male-en-edge
    provider: google
    voice: "en-US-Wavenet-D"
    language: en
    speed: "+0%"
    pitch: "+0Hz"

platforms:
  tiktok:
    enabled: true
    profile: female-vi-natural
    original_volume: 0.3
    tts_volume: 1.0
  youtube:
    enabled: true
    profile: female-en-natural
    original_volume: 0.3
    tts_volume: 1.0
  facebook:
    enabled: true
    profile: female-vi-natural
    original_volume: 0.3
    tts_volume: 1.0
  x:
    enabled: false
```

The `platforms.youtube.profile` reference is updated from `female-en-edge` to `female-en-natural` to match the rename.

### Pipeline launcher UI fix (`ui-app/src/pages/DownloadTranscribe.tsx`)

The pipeline launcher gains a voice picker that mirrors VideoDetail's TTS panel. Inserted in the existing TTS step, immediately after the Voice Profile selector (around line 577).

**Conditional rendering by provider:**

- **`provider === 'google'` or `provider === 'openai'`** → dropdown populated by `getTTSVoices(language, provider, apiKey)`. Same call VideoDetail uses. Auto-loads on provider change.
- **`provider === 'elevenlabs'`** → free-text "Voice ID" input with Save button, persisted to `localStorage['tts_voice_id_elevenlabs']`.

**Per-provider localStorage keys** (also retroactively applied in VideoDetail):

- `tts_voice_id_google`
- `tts_voice_id_openai`
- `tts_voice_id_elevenlabs`

The old shared `tts_voice_id` key gets migrated on first load (read the old value, write under the per-provider key matching the saved profile's provider, delete the old key). One-time migration that runs at first mount.

**Missing-API-key warning:**

Same banner pattern as VideoDetail (around `VideoDetail.tsx:681`): if the selected provider has `requires_key: true` and the matching localStorage key isn't set, render an amber warning with a "Configure" button that navigates to `/settings#apikeys`.

**`ttsOverrides` update** (currently `DownloadTranscribe.tsx:222-230`):

```ts
const ttsOverrides = {
  tts_provider: ttsProviderName || undefined,
  tts_voice: ttsVoiceId || undefined,    // ← now populated for ALL providers
  tts_api_key: ttsApiKey || undefined,
  llm_api_key: llmApiKey || undefined,
  llm_backend: llmBackend || undefined,
  playback_speed: playbackSpeed,
  underlay_db: underlayDb,
};
```

### VideoDetail per-provider voice ID storage

Same per-provider localStorage migration as DownloadTranscribe. `VideoDetail.tsx:360` currently reads `storageGet('tts_voice_id')` regardless of provider:

```ts
if (provider === 'elevenlabs') {
  const savedId = storageGet('tts_voice_id') || '';
  ...
}
```

Becomes:

```ts
if (provider === 'elevenlabs') {
  const savedId = storageGet('tts_voice_id_elevenlabs') || '';
  ...
} else if (provider === 'google') {
  // Validate saved Google voice against current voice list before pre-selecting.
  const savedId = storageGet('tts_voice_id_google') || '';
  ...
}
```

### Default provider changes

| Location | Old | New |
|---|---|---|
| `src/tts/__init__.py::get_tts_provider` fallback (line 27) | `"edge"` | `"google"` |
| `config/tts_voices.yaml::default_provider` | `edge` | `google` |
| `DownloadTranscribe.tsx:35` (`selectedTtsProvider` initial state) | `'edge'` | `'google'` |
| `VideoDetail.tsx:58` (`selectedTtsProvider` initial state) | `'elevenlabs'` | `'elevenlabs'` (unchanged) |

### Stale voice ID validation

On provider change in both VideoDetail and DownloadTranscribe, after voice list loads:

```ts
const savedId = storageGet(`tts_voice_id_${provider}`);
const isValid = ttsVoices.some(v => v.name === savedId);
if (savedId && !isValid) {
  storageSet(`tts_voice_id_${provider}`, '');
  // Optional: brief one-time UI hint that the saved voice was reset.
}
```

This protects users with a saved Edge voice from hitting "Voice not found" errors after the migration.

## Tests

### Backend test changes

- Delete `tests/test_tts.py::TestTTSFactory::test_get_edge_provider`.
- Delete `tests/test_tts.py::TestTTSFactory::test_default_provider_is_edge`.
- Delete `tests/test_tts.py::TestTTSFactory::test_config_default_provider` (currently asserts edge — would need full rewrite for google).
- Update `tests/test_tts.py::TestVoiceProfiles::test_load_profiles_missing_file` — change `assert profiles["default_provider"] == "edge"` to `== "google"`.
- Update `tests/test_tts.py::TestVoiceProfiles::test_save_and_load_profiles` — change default provider value in test fixtures.
- Add new test `TestTTSFactory::test_default_provider_is_google` asserting the new fallback.
- Add new test `TestTTSFactory::test_removed_providers_raise` asserting that `get_tts_provider({}, provider="edge")` raises `ValueError("Unknown TTS provider")`.

### UI test changes (manual smoke test, no automated UI tests in the repo)

- Open Settings, confirm only Anthropic / OpenAI / DeepSeek / ElevenLabs / Google appear in API Keys section (already true — no change needed).
- Open DownloadTranscribe, confirm provider dropdown shows only Google / OpenAI / ElevenLabs.
- Select Google + female-vi-natural → voice dropdown auto-loads with 8 Vietnamese voices (Standard A-D + Wavenet A-D).
- Pick `vi-VN-Wavenet-A`, run pipeline, confirm the API request to `/api/pipeline/full` includes `tts_voice: "vi-VN-Wavenet-A"`.
- Switch provider to ElevenLabs, confirm the voice dropdown is replaced by a free-text Voice ID input.
- Save a Voice ID, confirm it persists in `localStorage['tts_voice_id_elevenlabs']` (DevTools).
- Switch back to Google, confirm the dropdown reappears and the saved ElevenLabs ID is NOT used.

### Migration test

Add a test that simulates the old localStorage state (`tts_voice_id="vi-VN-HoaiMyNeural"`) and confirms it gets migrated to the per-provider key on first load. Skipped if UI test infrastructure isn't easily available — manual verification is acceptable.

## Migration path for existing users

A user with the current branch deployed locally would have:

- `localStorage['tts_voice_id']` possibly set to an Edge voice name.
- `localStorage['tts_provider']` (if it exists) set to `'edge'`.

On first load after this change:

1. If `localStorage['tts_voice_id']` exists, copy it to `tts_voice_id_<inferred-provider>` (default to elevenlabs since that's the only one that used the old key meaningfully). Delete the old key.
2. If the inferred provider's voice list doesn't contain the saved voice, clear the per-provider key.
3. Provider selector defaults to Google in DownloadTranscribe (was Edge).

No backend migration needed — config files are version-controlled.

## SSE event schema

No change. The `tts.complete` event still carries `sentence_plan`, `review_count`, `underlay_db`, `playback_speed`. The deleted providers were never sent on this event.

## Output artifacts

No change. The deleted providers wrote to the same `data/tts/{video_id}_{lang}_{provider}_{profile}.wav` path; existing artifacts on disk are not touched. Past dubs generated with Edge TTS will keep working (the WAV is a static file).

## Configuration

`config/config.yaml` may have `tts.default_provider: edge` or similar entries. Audit and update to `google` if present.

`config/config.example.yaml` updated to match.

## Open questions

None at draft time. Voice mappings are recommended by the user-approved design; per-provider localStorage keys are agreed; the rename of `*-edge` profiles to `*-natural` was confirmed in the design discussion.
