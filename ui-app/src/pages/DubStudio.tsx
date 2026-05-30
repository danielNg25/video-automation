import { useState, useEffect, useCallback, useRef } from 'react';
import { getTTSProviders, getTTSVoices, subscribeSSE } from '../api/client';
import {
  postStandaloneDub,
  getStandaloneDubs,
  deleteStandaloneDub,
  getStandaloneDubUrl,
} from '../api/standaloneDub';
import type { StandaloneDubEntry } from '../api/standaloneDub';
import type { TTSProviderInfo, VoiceInfo } from '../api/types';
import { loadApiKeys, loadLLMPrefs, storageGet, storageSet } from '../utils/storage';

// ── localStorage keys (isolated from video-flow keys) ────────────────────────

const SK = {
  provider: 'dub_studio_provider',
  language: 'dub_studio_language',
  playbackSpeed: 'dub_studio_playback_speed',
  enableShortening: 'dub_studio_enable_shortening',
  voiceId: (p: string) => `dub_studio_voice_id_${p}`,
  ttsApiKey: 'dub_studio_tts_api_key',
};

// ── small helpers ─────────────────────────────────────────────────────────────

function fmtDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ── component ─────────────────────────────────────────────────────────────────

export function DubStudioPage() {
  // ── form state ─────────────────────────────────────────────────────────────
  const [srtFile, setSrtFile] = useState<File | null>(null);
  const [provider, setProvider] = useState<string>(
    () => storageGet(SK.provider) || 'edge',
  );
  const [language, setLanguage] = useState<string>(
    () => storageGet(SK.language) || 'vi',
  );
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(() => {
    const v = parseFloat(storageGet(SK.playbackSpeed));
    return isNaN(v) ? 1.0 : v;
  });
  const [enableShortening, setEnableShortening] = useState<boolean>(() => {
    const v = storageGet(SK.enableShortening);
    return v === '' ? true : v === 'true';
  });
  const [voiceId, setVoiceId] = useState<string>(
    () => storageGet(SK.voiceId(storageGet(SK.provider) || 'edge')),
  );
  const [ttsApiKey, setTtsApiKey] = useState<string>(
    () => storageGet(SK.ttsApiKey),
  );

  // ── provider / voice lists ─────────────────────────────────────────────────
  const [providers, setProviders] = useState<TTSProviderInfo[]>([]);
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [loadingVoices, setLoadingVoices] = useState(false);

  // ── generation state ───────────────────────────────────────────────────────
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState<{ pct: number; message: string }>({
    pct: 0,
    message: '',
  });
  const [genError, setGenError] = useState('');
  const esRef = useRef<EventSource | null>(null);

  // ── recent dubs ────────────────────────────────────────────────────────────
  const [recentDubs, setRecentDubs] = useState<StandaloneDubEntry[]>([]);
  const [loadingRecent, setLoadingRecent] = useState(true);
  const [playingUuid, setPlayingUuid] = useState<string | null>(null);

  // ── API keys / LLM prefs from settings ────────────────────────────────────
  const apiKeys = loadApiKeys();
  const llmPrefs = loadLLMPrefs();

  // ── load providers once ────────────────────────────────────────────────────
  useEffect(() => {
    getTTSProviders()
      .then(setProviders)
      .catch(() => {/* silently ignore */});
  }, []);

  // ── load voices when provider or language changes ──────────────────────────
  useEffect(() => {
    setLoadingVoices(true);
    const key =
      ttsApiKey ||
      apiKeys[provider as keyof typeof apiKeys] ||
      undefined;
    getTTSVoices(language, provider, key)
      .then((v) => {
        setVoices(v);
        // restore persisted voice for this provider
        const saved = storageGet(SK.voiceId(provider));
        if (saved && v.some((vi) => vi.name === saved)) {
          setVoiceId(saved);
        } else if (v.length > 0) {
          setVoiceId(v[0].name);
        } else {
          setVoiceId('');
        }
      })
      .catch(() => setVoices([]))
      .finally(() => setLoadingVoices(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, language]);

  // ── load recent dubs ───────────────────────────────────────────────────────
  const refreshRecent = useCallback(async () => {
    try {
      const data = await getStandaloneDubs();
      setRecentDubs(data);
    } catch {
      // ignore
    } finally {
      setLoadingRecent(false);
    }
  }, []);

  useEffect(() => {
    void refreshRecent();
  }, [refreshRecent]);

  // ── persist preferences ────────────────────────────────────────────────────
  const handleSetProvider = (p: string) => {
    setProvider(p);
    storageSet(SK.provider, p);
    // restore voice for the newly selected provider
    const saved = storageGet(SK.voiceId(p));
    setVoiceId(saved);
  };

  const handleSetLanguage = (l: string) => {
    setLanguage(l);
    storageSet(SK.language, l);
  };

  const handleSetPlaybackSpeed = (s: number) => {
    setPlaybackSpeed(s);
    storageSet(SK.playbackSpeed, String(s));
  };

  const handleSetEnableShortening = (v: boolean) => {
    setEnableShortening(v);
    storageSet(SK.enableShortening, String(v));
  };

  const handleSetVoiceId = (v: string) => {
    setVoiceId(v);
    storageSet(SK.voiceId(provider), v);
  };

  const handleSetTtsApiKey = (v: string) => {
    setTtsApiKey(v);
    storageSet(SK.ttsApiKey, v);
  };

  // ── generate ───────────────────────────────────────────────────────────────
  const handleGenerate = async () => {
    if (!srtFile) return;
    setGenerating(true);
    setGenError('');
    setProgress({ pct: 0, message: 'Submitting…' });

    // close any previous SSE stream
    esRef.current?.close();

    try {
      const effectiveApiKey =
        ttsApiKey ||
        apiKeys[provider as keyof typeof apiKeys] ||
        undefined;

      const resp = await postStandaloneDub({
        file: srtFile,
        provider,
        voice: voiceId,
        language,
        playbackSpeed,
        enableShortening,
        apiKey: effectiveApiKey,
        llmApiKey: llmPrefs.backend !== '' ? (apiKeys[llmPrefs.backend as keyof typeof apiKeys] || undefined) : undefined,
        llmBackend: llmPrefs.backend || undefined,
      });

      // subscribe to SSE
      const es = subscribeSSE(resp.task_id, (eventType, data) => {
        if (eventType === 'progress') {
          setProgress({
            pct: typeof data.progress === 'number' ? data.progress : 0,
            message: typeof data.message === 'string' ? data.message : '',
          });
        } else if (eventType === 'complete') {
          setGenerating(false);
          setProgress({ pct: 100, message: 'Done!' });
          es.close();
          void refreshRecent();
        } else if (eventType === 'error') {
          setGenerating(false);
          setGenError(typeof data.message === 'string' ? data.message : 'Generation failed');
          es.close();
        }
      });
      esRef.current = es;
    } catch (err) {
      setGenerating(false);
      setGenError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  // ── delete ─────────────────────────────────────────────────────────────────
  const handleDelete = async (uuid: string) => {
    try {
      await deleteStandaloneDub(uuid);
      await refreshRecent();
    } catch {
      // ignore
    }
  };

  // ── file input ref ─────────────────────────────────────────────────────────
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── render ─────────────────────────────────────────────────────────────────
  const selectedProvider = providers.find((p) => p.id === provider);
  const requiresKey = selectedProvider?.requires_key ?? false;

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      {/* heading */}
      <div>
        <h1 className="text-2xl font-semibold">Dub Studio</h1>
        <p className="text-sm text-secondary mt-1">
          Convert any SRT subtitle file into a dubbed audio track.
        </p>
      </div>

      {/* form card */}
      <div className="card p-6 space-y-5">
        {/* SRT file picker */}
        <div>
          <label className="block text-sm font-medium mb-1">SRT file</label>
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="btn btn-secondary text-sm"
              onClick={() => fileInputRef.current?.click()}
            >
              {srtFile ? 'Change file' : 'Choose SRT file…'}
            </button>
            {srtFile && (
              <span className="text-sm text-secondary truncate max-w-xs">
                {srtFile.name}
              </span>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".srt"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setSrtFile(f);
            }}
          />
        </div>

        {/* Provider */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">TTS provider</label>
            <select
              className="input w-full"
              value={provider}
              onChange={(e) => handleSetProvider(e.target.value)}
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.free ? ' (free)' : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Language */}
          <div>
            <label className="block text-sm font-medium mb-1">Language</label>
            <select
              className="input w-full"
              value={language}
              onChange={(e) => handleSetLanguage(e.target.value)}
            >
              <option value="vi">Vietnamese</option>
              <option value="en">English</option>
              <option value="zh">Chinese</option>
            </select>
          </div>
        </div>

        {/* Voice */}
        <div>
          <label className="block text-sm font-medium mb-1">Voice</label>
          {loadingVoices ? (
            <p className="text-sm text-secondary">Loading voices…</p>
          ) : (
            <select
              className="input w-full"
              value={voiceId}
              onChange={(e) => handleSetVoiceId(e.target.value)}
            >
              {voices.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.friendly_name} ({v.gender})
                </option>
              ))}
              {voices.length === 0 && (
                <option value="">— no voices available —</option>
              )}
            </select>
          )}
        </div>

        {/* API key (shown only when required) */}
        {requiresKey && (
          <div>
            <label className="block text-sm font-medium mb-1">
              API key for {selectedProvider?.name}
            </label>
            <input
              type="password"
              className="input w-full font-mono text-sm"
              placeholder="sk-…"
              value={ttsApiKey}
              onChange={(e) => handleSetTtsApiKey(e.target.value)}
            />
          </div>
        )}

        {/* Playback speed + shortening */}
        <div className="grid grid-cols-2 gap-4 items-end">
          <div>
            <label className="block text-sm font-medium mb-1">
              Playback speed: {playbackSpeed.toFixed(2)}×
            </label>
            <input
              type="range"
              min={0.5}
              max={2.0}
              step={0.05}
              value={playbackSpeed}
              onChange={(e) => handleSetPlaybackSpeed(parseFloat(e.target.value))}
              className="w-full"
            />
          </div>
          <div className="flex items-center gap-2 pb-1">
            <input
              id="dub-studio-shorten"
              type="checkbox"
              checked={enableShortening}
              onChange={(e) => handleSetEnableShortening(e.target.checked)}
            />
            <label htmlFor="dub-studio-shorten" className="text-sm">
              Shorten dub to fit
            </label>
          </div>
        </div>

        {/* Progress bar */}
        {generating && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-secondary">
              <span>{progress.message}</span>
              <span>{progress.pct}%</span>
            </div>
            <div className="h-2 bg-surface-2 rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-all"
                style={{ width: `${progress.pct}%` }}
              />
            </div>
          </div>
        )}

        {/* Error */}
        {genError && (
          <p className="text-sm text-error">{genError}</p>
        )}

        {/* Submit */}
        <div className="flex justify-end">
          <button
            type="button"
            className="btn btn-primary"
            disabled={!srtFile || generating}
            onClick={() => void handleGenerate()}
            aria-label="Generate dub"
          >
            {generating ? 'Generating…' : 'Generate dub'}
          </button>
        </div>
      </div>

      {/* recent dubs */}
      <div className="card p-6 space-y-4">
        <h2 className="text-lg font-semibold">Recent dubs</h2>

        {loadingRecent ? (
          <p className="text-sm text-secondary">Loading…</p>
        ) : recentDubs.length === 0 ? (
          <p className="text-sm text-secondary">No dubs yet. Generate one above!</p>
        ) : (
          <ul className="space-y-3">
            {recentDubs.map((dub) => (
              <li
                key={dub.uuid}
                className="flex items-center gap-3 p-3 rounded-lg bg-surface-1"
              >
                {/* filename + meta */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">
                    {dub.original_filename}
                  </p>
                  <p className="text-xs text-secondary mt-0.5">
                    {dub.provider} · {dub.voice} · {dub.language.toUpperCase()} ·{' '}
                    {fmtDuration(dub.duration_seconds)} · {fmtSize(dub.file_size_bytes)} ·{' '}
                    {fmtDate(dub.created_at)}
                  </p>
                </div>

                {/* inline audio player */}
                {playingUuid === dub.uuid ? (
                  <audio
                    autoPlay
                    controls
                    className="h-8 w-48"
                    src={getStandaloneDubUrl(dub.uuid)}
                    onEnded={() => setPlayingUuid(null)}
                  />
                ) : (
                  <button
                    type="button"
                    className="btn btn-secondary text-xs"
                    onClick={() => setPlayingUuid(dub.uuid)}
                  >
                    Play
                  </button>
                )}

                {/* download */}
                <a
                  href={getStandaloneDubUrl(dub.uuid)}
                  download={`${dub.original_filename.replace(/\.srt$/i, '')}_dub.wav`}
                  className="btn btn-secondary text-xs"
                >
                  Download
                </a>

                {/* delete */}
                <button
                  type="button"
                  aria-label="Delete"
                  className="btn btn-secondary text-xs text-error"
                  onClick={() => void handleDelete(dub.uuid)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
