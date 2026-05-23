# TTS Providers Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the three free unreliable TTS providers (`edge`, `gtts`, `piper`), migrate all voice profiles to Google Wavenet equivalents, and fix the pipeline launcher's missing voice override so Google + OpenAI work end-to-end through the full pipeline.

**Architecture:** Backend deletions first (provider modules + factory branches + router list + pyproject deps + tests) — this is safe because the runner's default provider becomes Google. YAML migration second (voice profiles to Google equivalents, *-edge profiles renamed to *-natural). UI changes last: VideoDetail's localStorage migration to per-provider keys, then DownloadTranscribe gains a voice picker that mirrors VideoDetail (dropdown for Google/OpenAI, free-text input for ElevenLabs).

**Tech Stack:** Python 3.11+, pytest with pytest-asyncio (auto mode), ruff, React 19 + TypeScript, localStorage.

**Source spec:** [docs/superpowers/specs/2026-05-21-tts-providers-cleanup-design.md](../specs/2026-05-21-tts-providers-cleanup-design.md). All design decisions are locked in there.

**Branch:** `feature/phase4-dubbing-redesign-spec` (HEAD = 990adb3; spec committed).

---

## File Structure

**Files to delete:**
- `src/tts/edge.py`
- `src/tts/gtts_provider.py`
- `src/tts/piper_tts.py`

**Files to modify:**
- `src/tts/__init__.py` — remove three factory branches, change default from `"edge"` to `"google"`.
- `src/api/routers/tts.py` — remove three entries from `list_providers`.
- `pyproject.toml` — remove `edge-tts>=6.1.0` dependency and the `piper = [...]` optional-dependency line.
- `config/tts_voices.yaml` — migrate all 4 profiles to Google, rename `*-edge` profiles to `*-natural`, update `default_provider` and `platforms.youtube.profile` reference.
- `config/config.example.yaml` — change `tts.default_provider: edge` to `google` if the line exists.
- `tests/test_tts.py` — delete Edge-specific factory tests, update voice profile tests, add coverage for new default and removed providers.
- `ui-app/src/pages/VideoDetail.tsx` — migrate from shared `tts_voice_id` localStorage key to per-provider keys, with one-time migration on first mount.
- `ui-app/src/pages/DownloadTranscribe.tsx` — add voice picker UI block, populate `ttsOverrides.tts_voice` for all providers, missing-API-key warning, stale-voice-ID validation.
- `CHANGELOG.md` — `### Removed` entries for the three providers, `### Changed` entries for the migration and UI changes.

---

## Task 1: Backend — delete the three providers

**Files:**
- Delete: `src/tts/edge.py`
- Delete: `src/tts/gtts_provider.py`
- Delete: `src/tts/piper_tts.py`
- Modify: `src/tts/__init__.py`
- Modify: `src/api/routers/tts.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Update the factory in `src/tts/__init__.py`**

Replace lines 27-71 (the entire if/elif chain starting at `if provider_name == "edge":`) with:

```python
    tts_config = config.get("tts", {})
    provider_name = provider or tts_config.get("default_provider", "google")

    if provider_name == "google":
        from src.tts.google_tts import GoogleTTSProvider

        logger.info("Using Google Cloud TTS provider")
        return GoogleTTSProvider(config=tts_config)

    elif provider_name == "elevenlabs":
        from src.tts.elevenlabs import ElevenLabsTTSProvider

        api_key = tts_config.get("elevenlabs_api_key", "")
        model = tts_config.get("elevenlabs_model", "eleven_multilingual_v2")
        logger.info(f"Using ElevenLabs TTS provider (model={model})")
        return ElevenLabsTTSProvider(api_key=api_key, model=model)

    elif provider_name == "openai":
        from src.tts.openai_tts import OpenAITTSProvider

        api_key = tts_config.get("openai_api_key") or config.get("translation", {}).get("api_key")
        model = tts_config.get("openai_model", "tts-1")
        logger.info(f"Using OpenAI TTS provider (model={model})")
        return OpenAITTSProvider(api_key=api_key, model=model)

    else:
        raise ValueError(f"Unknown TTS provider: {provider_name}")
```

Note: factory default is now `"google"` (was `"edge"`). Order is Google → ElevenLabs → OpenAI (alphabetical-by-stability would also work; Google first since it's the new default).

- [ ] **Step 2: Update `src/api/routers/tts.py::list_providers`**

Replace lines 75-82 (the return list) with:

```python
    return [
        {"id": "google", "name": "Google Cloud TTS", "free": False, "requires_key": True},
        {"id": "elevenlabs", "name": "ElevenLabs", "free": False, "requires_key": True},
        {"id": "openai", "name": "OpenAI TTS", "free": False, "requires_key": True},
    ]
```

- [ ] **Step 3: Update `pyproject.toml`**

Remove line `    "edge-tts>=6.1.0",` from the `dependencies` array (around line 23).

Remove the entire line `piper = ["piper-tts>=1.2.0"]` (around line 30) from `[project.optional-dependencies]`.

Run `grep -n "gtts\b" pyproject.toml` — if it appears, also remove. (gtts may not have a direct dep — the `gtts_provider.py` may have imported it lazily.)

- [ ] **Step 4: Delete the three provider files**

```bash
rm src/tts/edge.py src/tts/gtts_provider.py src/tts/piper_tts.py
```

- [ ] **Step 5: Confirm no lingering imports**

```bash
grep -rn "from src.tts.edge\|from src.tts.gtts\|from src.tts.piper\|import edge_tts\|from gtts\|from piper" src/ tests/ ui-app/src/ 2>&1 | grep -v ".pyc:"
```
Expected: no output (no lingering references).

If there ARE references, fix them — they're likely in tests that need to be updated in Task 2, or stray imports anywhere else.

- [ ] **Step 6: Smoke test the factory**

```bash
python -c "
from src.tts import get_tts_provider
from src.tts.google_tts import GoogleTTSProvider
from src.tts.elevenlabs import ElevenLabsTTSProvider
from src.tts.openai_tts import OpenAITTSProvider

# Default → Google
p = get_tts_provider({})
assert isinstance(p, GoogleTTSProvider), f'got {type(p).__name__}'

# Explicit Google
p = get_tts_provider({}, provider='google')
assert isinstance(p, GoogleTTSProvider)

# Removed provider → ValueError
try:
    get_tts_provider({}, provider='edge')
    raise AssertionError('expected ValueError')
except ValueError as e:
    assert 'Unknown TTS provider' in str(e)

print('OK')
"
```
Expected output: `OK`.

If you see `ModuleNotFoundError: No module named 'src.tts.edge'`, something is still importing it — fix the import before proceeding.

- [ ] **Step 7: Lint**

```bash
ruff check src/tts/ src/api/routers/tts.py
```
Expected: no errors. If ruff flags unused imports in `src/tts/__init__.py` (from removed providers' lazy imports), they're already gone after Step 1 — but verify.

- [ ] **Step 8: Update README + CHANGELOG**

`README.md`: in the Tech Stack table, the TTS Dubbing row currently lists "Edge TTS (free), OpenAI, Google, ElevenLabs". Replace with `Google Cloud TTS, OpenAI, ElevenLabs`.

`CHANGELOG.md`: append to the `### Removed` block under `[Unreleased]` (or create one if missing — there are existing `### Removed` blocks; append to the FIRST one under `[Unreleased]`):

```
- Three free TTS providers (`edge`, `gtts`, `piper`) deleted along with their dependencies (`edge-tts`, `piper-tts`). Edge TTS in particular dropped ~40% of Vietnamese requests in production with `NoAudioReceived` errors. The factory now only knows `google`, `elevenlabs`, and `openai`; default fallback changed from `edge` to `google`. `list_providers` no longer surfaces the deleted entries.
```

- [ ] **Step 9: Commit**

```bash
git add src/tts/__init__.py src/api/routers/tts.py pyproject.toml README.md CHANGELOG.md
git rm src/tts/edge.py src/tts/gtts_provider.py src/tts/piper_tts.py
git commit -m "Remove edge / gtts / piper TTS providers

Edge TTS caused ~40% NoAudioReceived failures on real Vietnamese
runs. gTTS is unofficial Google Translate scraping. Piper is on-
device with lower quality. All three are removed in favour of the
three paid providers (Google Cloud TTS, ElevenLabs, OpenAI).

Factory default changes from edge to google. list_providers
returns only the three remaining providers."
```

---

## Task 2: Backend tests — update for new default

**Files:**
- Modify: `tests/test_tts.py`

- [ ] **Step 1: Read the current test file**

```bash
grep -n "test_get_edge\|test_default_provider_is_edge\|test_config_default_provider\|TestTTSFactory\|TestVoiceProfiles" tests/test_tts.py
```

The deletions target `TestTTSFactory::test_get_edge_provider`, `TestTTSFactory::test_default_provider_is_edge`, `TestTTSFactory::test_config_default_provider`. Voice profile tests need their `"edge"` default updated to `"google"`.

- [ ] **Step 2: Replace `TestTTSFactory` class**

Open `tests/test_tts.py`. Find the entire `class TestTTSFactory:` block (currently at lines 63-90 per the previous audit). Replace it with:

```python
class TestTTSFactory:
    def test_get_google_provider(self):
        from src.tts import get_tts_provider
        from src.tts.google_tts import GoogleTTSProvider

        provider = get_tts_provider({}, provider="google")
        assert isinstance(provider, GoogleTTSProvider)

    def test_default_provider_is_google(self):
        from src.tts import get_tts_provider
        from src.tts.google_tts import GoogleTTSProvider

        provider = get_tts_provider({})
        assert isinstance(provider, GoogleTTSProvider)

    def test_config_default_provider(self):
        from src.tts import get_tts_provider
        from src.tts.google_tts import GoogleTTSProvider

        config = {"tts": {"default_provider": "google"}}
        provider = get_tts_provider(config)
        assert isinstance(provider, GoogleTTSProvider)

    def test_unknown_provider_raises(self):
        from src.tts import get_tts_provider

        with pytest.raises(ValueError, match="Unknown TTS provider"):
            get_tts_provider({}, provider="nonexistent")

    def test_removed_providers_raise(self):
        """Edge, gtts, and Piper providers were deleted and now must raise."""
        from src.tts import get_tts_provider

        for removed in ("edge", "gtts", "piper"):
            with pytest.raises(ValueError, match="Unknown TTS provider"):
                get_tts_provider({}, provider=removed)
```

- [ ] **Step 3: Update voice profile tests**

In `tests/test_tts.py`, find `class TestVoiceProfiles:`. Update:

- `test_load_profiles_missing_file`: change `assert profiles["default_provider"] == "edge"` to `assert profiles["default_provider"] == "google"`.
- `test_save_and_load_profiles`: the test fixture data uses `"default_provider": "edge"` and `"provider": "edge"`. Change both to `"google"` and update the voice name from `"en-US-Test"` to `"en-US-Wavenet-A"` (a real Google voice name, even though the test doesn't actually call the API).

Show the current `test_save_and_load_profiles` fixture and inspect:

```bash
sed -n '113,135p' tests/test_tts.py
```

Then edit the literal values. Concretely the `data` dict in that test changes from:

```python
data = {
    "default_provider": "edge",
    "profiles": {"test-voice": {"provider": "edge", "voice": "en-US-Test", "language": "en"}},
    "platforms": {},
}
```

to:

```python
data = {
    "default_provider": "google",
    "profiles": {"test-voice": {"provider": "google", "voice": "en-US-Wavenet-A", "language": "en"}},
    "platforms": {},
}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_tts.py tests/test_tts_planner.py -v
```
Expected: all tests pass. If a non-factory test fails because of a removed module import (e.g. a test imports `EdgeTTSProvider` deep in a fixture), grep and fix:

```bash
grep -n "EdgeTTSProvider\|GTTSProvider\|PiperTTSProvider" tests/
```

- [ ] **Step 5: Lint**

```bash
ruff check tests/test_tts.py
```
Expected: no new errors (pre-existing lint warnings in this file may persist — that's fine).

- [ ] **Step 6: Update CHANGELOG**

Append to existing `### Changed` block under `[Unreleased]`:

```
- TTS factory tests in `tests/test_tts.py` updated for the new default provider (`google`). New test `test_removed_providers_raise` pins that `edge`, `gtts`, and `piper` now raise `ValueError`.
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_tts.py CHANGELOG.md
git commit -m "Update TTS factory tests for Google default

Old TestTTSFactory tests asserted Edge as default and instantiated
EdgeTTSProvider. Replaced with Google-equivalent tests plus a new
test_removed_providers_raise that pins the deletion of edge/gtts/
piper. Voice profile tests' fixtures updated to use Google as
default_provider."
```

---

## Task 3: Voice profiles YAML migration

**Files:**
- Modify: `config/tts_voices.yaml`
- Modify: `config/config.example.yaml`

- [ ] **Step 1: Confirm current content**

```bash
cat config/tts_voices.yaml
```

The current profiles all have `provider: edge` and Edge voice names. Two profiles (`female-en-edge`, `male-en-edge`) have "edge" in the name.

- [ ] **Step 2: Replace `config/tts_voices.yaml` entirely**

Overwrite with:

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
  female-en-natural:
    provider: google
    voice: "en-US-Wavenet-C"
    language: en
    speed: "+0%"
    pitch: "+0Hz"
  male-en-natural:
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

Note: `platforms.youtube.profile` updated from `female-en-edge` → `female-en-natural` to match the rename.

- [ ] **Step 3: Update `config/config.example.yaml` if it references `edge`**

```bash
grep -n "edge\|default_provider" config/config.example.yaml
```

If the file has a `default_provider: edge` line under `tts:`, change it to `google`. If it has any Edge-specific config keys (e.g. an `edge_*` entry), delete them. If no edge references appear, skip this step.

Also check `config/config.yaml`:

```bash
grep -n "edge\|default_provider" config/config.yaml
```

Update the same way. Note: `config/config.yaml` is gitignored (per the dubbing redesign PR) — fine to edit locally but it won't be committed.

- [ ] **Step 4: Verify YAML parses**

```bash
python -c "
import yaml
with open('config/tts_voices.yaml') as f:
    data = yaml.safe_load(f)
assert data['default_provider'] == 'google'
assert set(data['profiles'].keys()) == {'female-vi-natural', 'male-vi-natural', 'female-en-natural', 'male-en-natural'}
assert data['platforms']['youtube']['profile'] == 'female-en-natural'
assert all(p['provider'] == 'google' for p in data['profiles'].values())
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 5: Run the voice-profile tests**

```bash
python -m pytest tests/test_tts.py::TestVoiceProfiles -v
```
Expected: all pass. The test `test_load_profiles_from_file` reads the actual `config/tts_voices.yaml` — confirm it still finds `female-vi-natural`:

```bash
grep -n "female-vi-natural" tests/test_tts.py
```

The existing assertion `assert "female-vi-natural" in profiles["profiles"]` should still pass since we kept that name.

- [ ] **Step 6: Update CHANGELOG**

Append to existing `### Changed` block under `[Unreleased]`:

```
- `config/tts_voices.yaml` migrated from Edge voice names to Google Wavenet equivalents. Profiles renamed: `female-en-edge` → `female-en-natural`, `male-en-edge` → `male-en-natural`. `platforms.youtube.profile` reference updated to match. `default_provider` changed from `edge` to `google`.
```

- [ ] **Step 7: Commit**

```bash
git add config/tts_voices.yaml config/config.example.yaml CHANGELOG.md
git commit -m "Migrate voice profiles from Edge to Google Wavenet

All 4 voice profiles in tts_voices.yaml switch from Edge voice
names (vi-VN-HoaiMyNeural, vi-VN-NamMinhNeural, en-US-JennyNeural,
en-US-GuyNeural) to Google Wavenet equivalents (vi-VN-Wavenet-A
through D, en-US-Wavenet-C/D). The two profiles with 'edge' in the
name rename to '*-natural'. platforms.youtube.profile reference
updated. default_provider changes to google."
```

---

## Task 4: VideoDetail — per-provider localStorage migration

**Files:**
- Modify: `ui-app/src/pages/VideoDetail.tsx`

This task migrates the shared `tts_voice_id` localStorage key to per-provider keys (`tts_voice_id_google`, `tts_voice_id_openai`, `tts_voice_id_elevenlabs`). It also adds stale-voice-ID validation when the saved value doesn't match the current provider's voice list. The component's existing voice picker UI (dropdown vs free-text) is unchanged.

- [ ] **Step 1: Add a one-time migration helper**

Near the top of `VideoDetail.tsx` (before the component, after imports), add:

```tsx
/**
 * One-time migration: the old shared `tts_voice_id` localStorage key holds a
 * value from before per-provider keys existed. Move it to whichever provider-
 * specific key matches the user's last-selected provider. Delete the old key.
 *
 * Runs at most once per browser. Safe to call on every mount.
 */
function migrateLegacyVoiceId(currentProvider: string): void {
  const legacy = localStorage.getItem('tts_voice_id');
  if (!legacy) return;
  const targetKey = `tts_voice_id_${currentProvider}`;
  if (!localStorage.getItem(targetKey)) {
    localStorage.setItem(targetKey, legacy);
  }
  localStorage.removeItem('tts_voice_id');
}
```

- [ ] **Step 2: Update the `selectedVoiceId` and `voiceIdInput` initial state**

Around lines 62-63:

```tsx
const [selectedVoiceId, setSelectedVoiceId] = useState(() => storageGet('tts_voice_id') || '');
const [voiceIdInput, setVoiceIdInput] = useState(() => storageGet('tts_voice_id') || '');
```

Replace with:

```tsx
const [selectedVoiceId, setSelectedVoiceId] = useState(() => {
  const provider = storageGet('tts_selected_provider') || 'elevenlabs';
  return storageGet(`tts_voice_id_${provider}`) || storageGet('tts_voice_id') || '';
});
const [voiceIdInput, setVoiceIdInput] = useState(() => {
  const provider = storageGet('tts_selected_provider') || 'elevenlabs';
  return storageGet(`tts_voice_id_${provider}`) || storageGet('tts_voice_id') || '';
});
```

Note: the fallback to `'tts_voice_id'` covers users whose state hasn't been migrated yet on first mount.

- [ ] **Step 3: Run migration on first mount**

Find the existing `useEffect` near the top of the component (after the state declarations). Add a new `useEffect` block:

```tsx
useEffect(() => {
  migrateLegacyVoiceId(selectedTtsProvider);
}, []);   // run once on mount
```

- [ ] **Step 4: Update `handleTtsProviderChange`**

Around line 354. Replace the function body. Current:

```tsx
const handleTtsProviderChange = (provider: string) => {
  setSelectedTtsProvider(provider);
  setTtsVoices([]);
  setTtsGenerated(false);
  if (provider === 'elevenlabs') {
    const savedId = storageGet('tts_voice_id') || '';
    setSelectedVoiceId(savedId);
    setVoiceIdInput(savedId);
  } else {
    setSelectedVoiceId('');
    setVoiceIdInput('');
    const info = ttsProviders.find(p => p.id === provider);
    if (info && !info.requires_key) {
      loadVoicesForProvider(provider);
    } else {
      const keys = loadApiKeys();
      const key = keys[provider] || '';
      if (key) loadVoicesForProvider(provider, key);
    }
  }
};
```

Replace with:

```tsx
const handleTtsProviderChange = (provider: string) => {
  setSelectedTtsProvider(provider);
  storageSet('tts_selected_provider', provider);
  setTtsVoices([]);
  setTtsGenerated(false);
  const savedId = storageGet(`tts_voice_id_${provider}`) || '';
  if (provider === 'elevenlabs') {
    // Free-text input: trust the saved value (user pastes IDs manually).
    setSelectedVoiceId(savedId);
    setVoiceIdInput(savedId);
  } else {
    // Dropdown providers: load voice list, then validate saved ID against it.
    setSelectedVoiceId(savedId);
    setVoiceIdInput('');
    const info = ttsProviders.find(p => p.id === provider);
    const keys = loadApiKeys();
    const key = keys[provider] || '';
    if (info && !info.requires_key) {
      loadVoicesForProvider(provider);
    } else if (key) {
      loadVoicesForProvider(provider, key);
    }
  }
};
```

- [ ] **Step 5: Update `loadVoicesForProvider` to validate the saved ID**

Around line 153:

```tsx
const loadVoicesForProvider = useCallback(async (provider: string, apiKey?: string, language?: string) => {
  try {
    const voices = await getTTSVoices(language || ttsLanguage, provider, apiKey);
    setTtsVoices(voices);
    if (voices.length > 0) {
      setSelectedVoiceId(voices[0].name);
    }
  } catch {
    setTtsVoices([]);
  }
}, []);
```

Replace with:

```tsx
const loadVoicesForProvider = useCallback(async (provider: string, apiKey?: string, language?: string) => {
  try {
    const voices = await getTTSVoices(language || ttsLanguage, provider, apiKey);
    setTtsVoices(voices);
    if (voices.length > 0) {
      // Honor the saved voice ID if it's still valid for this provider; else
      // fall back to the first voice in the list.
      const saved = storageGet(`tts_voice_id_${provider}`) || '';
      const isValid = saved && voices.some(v => v.name === saved);
      const picked = isValid ? saved : voices[0].name;
      setSelectedVoiceId(picked);
      if (!isValid && saved) {
        // Saved value was stale — clear it so the user knows the dropdown is authoritative.
        storageSet(`tts_voice_id_${provider}`, '');
      }
    }
  } catch {
    setTtsVoices([]);
  }
}, [ttsLanguage]);
```

- [ ] **Step 6: Update the ElevenLabs Voice ID save button**

Around line 710 (inside the ElevenLabs voice ID input JSX). Current:

```tsx
storageSet('tts_voice_id', voiceIdInput);
```

Replace with:

```tsx
storageSet(`tts_voice_id_${selectedTtsProvider}`, voiceIdInput);
```

- [ ] **Step 7: Persist the dropdown's voice selection too**

For Google/OpenAI, the dropdown's `onChange` currently only sets local state. Add a `storageSet` call. Around line 729-730 (the dropdown's onChange):

Current:
```tsx
onChange={(e) => { setSelectedVoiceId(e.target.value); setTtsGenerated(false); }}
```

Replace with:
```tsx
onChange={(e) => {
  setSelectedVoiceId(e.target.value);
  storageSet(`tts_voice_id_${selectedTtsProvider}`, e.target.value);
  setTtsGenerated(false);
}}
```

- [ ] **Step 8: Verify build**

```bash
cd ui-app && npm run lint 2>&1 | tail -20
```
Expected: no NEW errors (the file has pre-existing lint warnings — those persist).

Also run a build to catch TS errors:
```bash
cd ui-app && npx tsc --noEmit 2>&1 | tail -20
```
Expected: clean (or only pre-existing TS errors unrelated to this change).

- [ ] **Step 9: Manual smoke test**

If the dev server is running, refresh VideoDetail. Otherwise skip — Task 7 handles end-to-end manual QA.

Verify in DevTools:
- `localStorage.getItem('tts_voice_id')` is `null` after first mount (migrated and deleted).
- `localStorage.getItem('tts_voice_id_elevenlabs')` (or whichever provider you had) holds the migrated value.

- [ ] **Step 10: Update CHANGELOG**

Append to existing `### Changed` block under `[Unreleased]`:

```
- VideoDetail TTS panel: voice IDs now stored under per-provider localStorage keys (`tts_voice_id_google`, `tts_voice_id_openai`, `tts_voice_id_elevenlabs`) instead of a single shared `tts_voice_id`. One-time migration on mount moves the legacy key to the per-provider slot matching the user's last-selected provider. Stale voice IDs (e.g. an Edge voice name saved before the provider cleanup) are auto-cleared when they don't match the loaded voice list.
```

- [ ] **Step 11: Commit**

```bash
git add ui-app/src/pages/VideoDetail.tsx CHANGELOG.md
git commit -m "VideoDetail: per-provider localStorage keys for voice IDs

The old shared tts_voice_id key conflated voice IDs across providers
— a Google voice name like vi-VN-Wavenet-A could leak into the
ElevenLabs free-text input. Now stored under per-provider keys:
tts_voice_id_google, tts_voice_id_openai, tts_voice_id_elevenlabs.

One-time mount-time migration moves the legacy value to the slot
matching the user's last-selected provider. Stale voice IDs (e.g.
saved Edge voice names from before the provider cleanup) are
detected against the live voice list and cleared so the dropdown's
first entry becomes authoritative."
```

---

## Task 5: DownloadTranscribe — add voice picker

**Files:**
- Modify: `ui-app/src/pages/DownloadTranscribe.tsx`

The pipeline launcher gains the same voice picker pattern as VideoDetail. Conditional rendering by provider:
- Google / OpenAI: dropdown auto-loaded from `getTTSVoices(language, provider, apiKey)`.
- ElevenLabs: free-text Voice ID input with Save button and per-provider localStorage key.

Also adds a missing-API-key warning banner (mirrors VideoDetail).

- [ ] **Step 1: Add state for the voice picker**

In `DownloadTranscribe.tsx`, near the top of the component where other TTS-related state is declared (around line 35-41), add:

```tsx
const [ttsVoices, setTtsVoices] = useState<VoiceInfo[]>([]);
const [selectedVoiceId, setSelectedVoiceId] = useState(() => {
  const provider = storageGet('tts_selected_provider') || 'google';
  return storageGet(`tts_voice_id_${provider}`) || '';
});
const [voiceIdInput, setVoiceIdInput] = useState(() => {
  return storageGet('tts_voice_id_elevenlabs') || '';
});
const [voiceIdSaved, setVoiceIdSaved] = useState(false);
const [ttsApiKey, setTtsApiKey] = useState('');
```

Also import `VoiceInfo` from the same module where VideoDetail imports it. Use the existing import line in DownloadTranscribe and add `VoiceInfo` to the type imports. Use grep first:

```bash
grep -n "VoiceInfo\|getTTSVoices" ui-app/src/pages/DownloadTranscribe.tsx ui-app/src/pages/VideoDetail.tsx
```

Mirror VideoDetail's import.

- [ ] **Step 2: Load voices when provider changes**

Add a `useEffect` after the state declarations:

```tsx
useEffect(() => {
  // Load voice list for the selected provider (skipped for ElevenLabs —
  // user enters Voice ID by hand).
  if (selectedTtsProvider === 'elevenlabs') {
    setTtsVoices([]);
    setSelectedVoiceId(storageGet('tts_voice_id_elevenlabs') || '');
    setVoiceIdInput(storageGet('tts_voice_id_elevenlabs') || '');
    return;
  }
  const keys = loadApiKeys();
  const key = keys[selectedTtsProvider] || '';
  setTtsApiKey(key);
  if (!key) {
    setTtsVoices([]);
    return;
  }
  (async () => {
    try {
      const voices = await getTTSVoices(undefined, selectedTtsProvider, key);
      setTtsVoices(voices);
      const saved = storageGet(`tts_voice_id_${selectedTtsProvider}`) || '';
      const isValid = saved && voices.some(v => v.name === saved);
      const picked = isValid ? saved : (voices[0]?.name || '');
      setSelectedVoiceId(picked);
      if (!isValid && saved) {
        storageSet(`tts_voice_id_${selectedTtsProvider}`, '');
      }
    } catch {
      setTtsVoices([]);
    }
  })();
}, [selectedTtsProvider]);
```

Make sure `getTTSVoices` and `storageGet`/`storageSet` and `loadApiKeys` are imported. Mirror VideoDetail's imports.

- [ ] **Step 3: Persist provider selection**

Find the existing `selectedTtsProvider` state setter (line 35: `useState('edge')`). Change initial value to `'google'`:

```tsx
const [selectedTtsProvider, setSelectedTtsProvider] = useState(() =>
  storageGet('tts_selected_provider') || 'google'
);
```

Find the `<select>` for provider (around line 564). Update its `onChange`:

```tsx
onChange={(e) => {
  setSelectedTtsProvider(e.target.value);
  storageSet('tts_selected_provider', e.target.value);
}}
```

- [ ] **Step 4: Update the ttsOverrides voice resolution**

Around line 217-225, replace:

```tsx
const ttsApiKey =
  ttsProviderName === 'elevenlabs' ? apiKeys.elevenlabs :
  ttsProviderName === 'openai' ? apiKeys.openai :
  ttsProviderName === 'google' ? apiKeys.google : '';
const ttsVoiceId = (ttsProviderName === 'elevenlabs' ? (storageGet('tts_voice_id') || '') : '');
```

With:

```tsx
const ttsApiKey =
  ttsProviderName === 'elevenlabs' ? apiKeys.elevenlabs :
  ttsProviderName === 'openai' ? apiKeys.openai :
  ttsProviderName === 'google' ? apiKeys.google : '';
// All providers now send a voice override (the fix).
const ttsVoiceId = storageGet(`tts_voice_id_${ttsProviderName}`) || selectedVoiceId || '';
```

- [ ] **Step 5: Render the voice picker JSX**

Inside the TTS step rendering (around line 559, inside `{step.key === 'tts' && ...}`), after the existing Provider + Voice Profile grid (around line 578) but BEFORE the Dub Playback Speed row, insert:

```tsx
{/* Missing API key warning */}
{ttsProviders.find(p => p.id === selectedTtsProvider)?.requires_key && !ttsApiKey && (
  <div className="bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs p-3 rounded-lg flex items-center gap-2">
    <span className="material-symbols-outlined text-sm">warning</span>
    <span>No API key configured for <strong>{selectedTtsProvider}</strong>.</span>
    <button
      onClick={() => navigate('/settings#apikeys')}
      className="ml-auto text-[10px] font-bold uppercase tracking-wider text-amber-300 hover:text-amber-200 flex items-center gap-1 whitespace-nowrap"
    >
      <span className="material-symbols-outlined text-xs">settings</span>
      Configure
    </button>
  </div>
)}

{/* ElevenLabs: Voice ID input */}
{selectedTtsProvider === 'elevenlabs' && (
  <div className="space-y-2">
    <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block">Voice ID</label>
    <div className="flex gap-2">
      <input
        type="text"
        value={voiceIdInput}
        onChange={(e) => { setVoiceIdInput(e.target.value); setVoiceIdSaved(false); }}
        placeholder="Paste ElevenLabs voice ID"
        className="flex-1 bg-surface-container border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary placeholder:text-zinc-600 font-mono"
      />
      <button
        onClick={() => {
          setSelectedVoiceId(voiceIdInput);
          storageSet('tts_voice_id_elevenlabs', voiceIdInput);
          setVoiceIdSaved(true);
          setTimeout(() => setVoiceIdSaved(false), 2000);
        }}
        disabled={!voiceIdInput}
        className="px-3 py-2 rounded text-[10px] font-bold uppercase bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-50 transition-colors"
      >
        {voiceIdSaved ? 'Saved' : 'Save'}
      </button>
    </div>
  </div>
)}

{/* Google / OpenAI: voice dropdown */}
{selectedTtsProvider !== 'elevenlabs' && (
  <div className="space-y-1">
    <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block">Voice</label>
    <select
      value={selectedVoiceId}
      onChange={(e) => {
        setSelectedVoiceId(e.target.value);
        storageSet(`tts_voice_id_${selectedTtsProvider}`, e.target.value);
      }}
      className="w-full bg-surface-container border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
    >
      {ttsVoices.length === 0 && <option value="">No voices loaded (check API key)</option>}
      {ttsVoices.map((v) => (
        <option key={v.name} value={v.name}>
          {v.friendly_name || v.name} ({v.gender}) — {v.language}
        </option>
      ))}
    </select>
  </div>
)}
```

Also make sure `navigate` is available — check the existing imports for `useNavigate` from react-router:

```bash
grep -n "useNavigate\|navigate(" ui-app/src/pages/DownloadTranscribe.tsx | head
```

If not present, import and instantiate it the same way VideoDetail does:

```tsx
import { useNavigate } from 'react-router-dom';
// inside the component:
const navigate = useNavigate();
```

- [ ] **Step 6: Verify build**

```bash
cd ui-app && npm run lint 2>&1 | tail -20
cd ui-app && npx tsc --noEmit 2>&1 | tail -20
```
Expected: no NEW errors. (Pre-existing lint warnings persist.)

- [ ] **Step 7: Manual smoke test (if dev server running)**

Reload DownloadTranscribe. Confirm:
- Provider dropdown shows only Google / OpenAI / ElevenLabs.
- Default provider is Google.
- Switching to Google with a saved API key auto-loads the 8 Vietnamese voices in the dropdown.
- Switching to ElevenLabs shows the free-text Voice ID input.
- Saving an ElevenLabs voice ID persists to `localStorage['tts_voice_id_elevenlabs']` (check in DevTools).

If the dev server isn't running, Task 7 handles full manual QA.

- [ ] **Step 8: Update CHANGELOG**

Append to existing `### Fixed` block under `[Unreleased]` (or `### Changed`):

```
- Pipeline launcher (DownloadTranscribe) now supports voice override for all providers, not just ElevenLabs. Previously Google + OpenAI inherited the voice from the profile (which used Edge voice names), so the runner would pass an Edge name like `vi-VN-HoaiMyNeural` to Google's API and get rejected. The launcher gains a voice picker that mirrors VideoDetail: dropdown for Google/OpenAI (auto-loaded when the provider's API key is configured), free-text Voice ID input for ElevenLabs. Missing-API-key banner warns when the selected provider has no saved key. Voice IDs persist under per-provider localStorage keys; stale voices (saved with the old shared key, or for a different provider) are cleared automatically.
```

- [ ] **Step 9: Commit**

```bash
git add ui-app/src/pages/DownloadTranscribe.tsx CHANGELOG.md
git commit -m "Pipeline launcher: voice picker for all providers

The pipeline launcher previously sent a voice override only for
ElevenLabs (line 221 in the old code). Google and OpenAI inherited
the profile's voice — which was an Edge voice name like
vi-VN-HoaiMyNeural — and the runner forwarded that to Google's
API, which rejected it with 'Voice not found'.

The launcher now has the same voice picker as the Video Studio TTS
panel: dropdown for Google/OpenAI (auto-loaded), free-text Voice ID
input for ElevenLabs (with save button + per-provider localStorage
key). Missing-API-key warning banner mirrors VideoDetail. Default
provider changes from edge to google."
```

---

## Task 6: Verify the full pipeline end-to-end

**Files:**
- No code changes — manual verification + CHANGELOG finalisation.

- [ ] **Step 1: Run full automated test suite**

```bash
make test
```

Or if `make test` isn't available:

```bash
python -m pytest tests/ -v -x --ignore=tests/test_integration.py
```

Expected: all tests pass. If any test fails, it's likely a deleted-provider reference — grep and fix:

```bash
grep -rn "edge_tts\|EdgeTTSProvider\|GTTSProvider\|PiperTTSProvider\|from src.tts.edge\|from src.tts.gtts\|from src.tts.piper" src/ tests/
```

- [ ] **Step 2: Rebuild Docker and start the app**

```bash
make docker-up
```

Wait for the build to finish, then tail logs:

```bash
make docker-logs
```

Expected: app starts cleanly. Specifically watch for `ImportError` or `ModuleNotFoundError` for any deleted module — none should appear.

- [ ] **Step 3: UI smoke check — Settings → API Keys**

In a browser at `http://localhost:8000`:
- Open Settings → API Keys.
- Confirm only these entries appear: Anthropic, OpenAI, DeepSeek, ElevenLabs, Google Cloud.
- (The Anthropic / DeepSeek entries are for LLM translation, not TTS — they stay.)

- [ ] **Step 4: UI smoke check — Pipeline launcher**

- Open DownloadTranscribe.
- Default provider should be Google.
- With a saved Google Cloud API key (`AIza...`), the voice dropdown should auto-load 8 Vietnamese voices (`vi-VN-Standard-A` through `vi-VN-Wavenet-D`).
- Pick `vi-VN-Wavenet-A`.
- Open the request body inspector (or use `curl`/UI dev tools). When you start a pipeline, the POST body should include `tts_voice: "vi-VN-Wavenet-A"`.
- Switch the provider to ElevenLabs in the dropdown. The voice dropdown should be replaced by a free-text input.

- [ ] **Step 5: UI smoke check — VideoDetail**

- Open any existing video's Video Studio.
- The TTS panel should default to ElevenLabs (unchanged from the spec).
- Switch to Google. Voice dropdown loads 8 Vietnamese voices.
- Switch back to ElevenLabs. The free-text Voice ID input reappears with the saved ID (if any).
- DevTools `localStorage`: confirm `tts_voice_id` is gone, and the per-provider keys (`tts_voice_id_elevenlabs`, `tts_voice_id_google` etc.) are populated as you save them.

- [ ] **Step 6: Run one end-to-end pipeline with Google TTS**

Pick a URL from `testurl.txt` (e.g. https://v.douyin.com/ZR7CUvUjn3U/).

In the pipeline launcher:
- Provider: Google
- Voice profile: female-vi-natural
- Voice: vi-VN-Wavenet-A
- Dub Playback Speed: 1.5×
- Underlay: -12 dB

Start the pipeline. Watch the logs:

```bash
make docker-logs | tee /tmp/pipeline.log
```

Expected outcomes:
- No `NoAudioReceived` warnings (we deleted Edge TTS — Google doesn't drop requests like that).
- No `Voice not found` errors from Google.
- TTS stage completes.
- Final dub WAV exists at `data/tts/{video_id}_vi_google_female-vi-natural.wav`.
- `data/srt/{video_id}_vi.dubsync.srt` is written.
- `data/output/{video_id}_*.mp4` files are produced for the platforms.

Listen to the final WAV — confirm it sounds like a clean Vietnamese dub with the Chinese underlay audible underneath.

If anything fails here, STOP and diagnose. Do NOT mark the task complete.

- [ ] **Step 7: README + CHANGELOG finalisation**

`CHANGELOG.md`: The `[Unreleased]` block has accumulated entries from this work. Keep them as-is (no consolidation needed — they're informative).

`README.md`: in the "Tech Stack" table, confirm the TTS Dubbing row now reads `Google Cloud TTS, OpenAI, ElevenLabs` (not `Edge TTS (free), OpenAI, Google, ElevenLabs`). If you missed this in Task 1 Step 8, fix it now.

- [ ] **Step 8: Final commit (if any docs changes from this task)**

If README or any docs were touched in Step 7:

```bash
git add README.md
git commit -m "Document Google as primary TTS provider

Tech Stack table updated to reflect the three remaining providers
after the edge/gtts/piper cleanup. Google Cloud TTS leads as the
new default."
```

If nothing changed in this task, no commit is needed.

- [ ] **Step 9: Push the branch**

```bash
git push origin feature/phase4-dubbing-redesign-spec
```

The branch was already pushed during the previous PR cycle; this is just a sync.

---

## Self-Review Checklist

**Spec coverage:**

- ✅ §Provider matrix (delete edge/gtts/piper, keep google/elevenlabs/openai) — Task 1
- ✅ §Backend deletions (provider files, factory branches, pyproject deps, router list) — Task 1
- ✅ §Voice profile migration (4 profiles → Google equivalents, *-edge rename) — Task 3
- ✅ §Pipeline launcher UI fix (voice picker for all providers, missing-API-key warning) — Task 5
- ✅ §VideoDetail per-provider voice ID storage — Task 4
- ✅ §Default provider changes (factory, YAML, DownloadTranscribe initial state) — Tasks 1, 3, 5
- ✅ §Stale voice ID validation (clear when not in current provider's voice list) — Tasks 4, 5
- ✅ §Tests (delete edge tests, add removed-providers test, update voice profile fixtures) — Task 2
- ✅ §Migration path for existing users (one-time localStorage migration on mount) — Task 4
- ✅ §Config — config.yaml / config.example.yaml updated if needed — Task 3 Step 3
- ✅ §What stays (BaseTTSProvider, runner API-key injection, Settings UI) — implicitly preserved by these tasks not touching them

**Placeholder scan:**

- No "TBD", "TODO", "fill in details" — checked.
- No "Add appropriate error handling" — concrete handling specified in Tasks 4 Step 5 and Task 5 Step 5.
- No "Write tests for the above" — Task 2 has explicit test code.
- No "Similar to Task N" — Tasks 4 and 5 share UI patterns but the code is fully repeated in each task.
- No references to undefined types or functions — `loadApiKeys`, `storageGet`, `storageSet`, `getTTSVoices`, `VoiceInfo`, `useNavigate` are all referenced from existing usage in VideoDetail; the grep commands in the steps confirm their availability.

**Type consistency:**

- localStorage keys: `tts_voice_id_google`, `tts_voice_id_openai`, `tts_voice_id_elevenlabs`, `tts_selected_provider` — used identically in Tasks 4 and 5.
- Profile names: `female-vi-natural`, `male-vi-natural`, `female-en-natural`, `male-en-natural` — used identically in Tasks 2, 3, and 6.
- Default provider: `google` — set identically in Tasks 1 (factory), 3 (YAML), and 5 (UI initial state).
- Provider strings: `google`, `elevenlabs`, `openai` (lowercase) — consistent across backend + frontend.

**Known minor risks (call out but no plan change):**

- Task 5 Step 1: importing `VoiceInfo` requires it to be exported from wherever it's currently imported in VideoDetail. If the type is defined inline somewhere unusual, the import will fail and need adjustment — the grep in Step 1 will catch this.
- Task 6 Step 6: the end-to-end pipeline test relies on the user having a valid Google Cloud API key configured. If they haven't completed the GCP setup yet, this step blocks until they do. The plan assumes the user is ready — if not, mark Task 6 as DONE_WITH_CONCERNS and document.
- Task 1 Step 4 uses `git rm` which removes the file from the working tree AND stages the deletion. If the files have local-only modifications, they'd be lost. Verify with `git status` first.
