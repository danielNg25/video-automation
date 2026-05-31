import { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { cancelTask, getTTSProviders, getTTSVoices, subscribeSSE } from '../api/client';
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
    () => storageGet(SK.provider) || 'google',
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
    () => storageGet(SK.voiceId(storageGet(SK.provider) || 'google')),
  );

  // ── provider / voice lists ─────────────────────────────────────────────────
  const [providers, setProviders] = useState<TTSProviderInfo[]>([]);
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [loadingVoices, setLoadingVoices] = useState(false);
  const [missingKey, setMissingKey] = useState(false);

  // ── generation state ───────────────────────────────────────────────────────
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState<{ pct: number; message: string }>({
    pct: 0,
    message: '',
  });
  const [genError, setGenError] = useState('');
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  // ── recent dubs ────────────────────────────────────────────────────────────
  const [recentDubs, setRecentDubs] = useState<StandaloneDubEntry[]>([]);
  const [loadingRecent, setLoadingRecent] = useState(true);
  const [playingUuid, setPlayingUuid] = useState<string | null>(null);

  // ── load providers once ────────────────────────────────────────────────────
  useEffect(() => {
    getTTSProviders()
      .then((list) => {
        setProviders(list);
        // If the persisted provider isn't in the BE list (e.g. stale 'edge'
        // from before Edge TTS was removed), fall back to the first one so
        // the voice-load doesn't hit a 500.
        if (list.length > 0 && !list.some((p) => p.id === provider)) {
          handleSetProvider(list[0].id);
        }
      })
      .catch(() => {/* silently ignore */});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── SSE cleanup on unmount ─────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

  // ── load voices when provider or language changes ──────────────────────────
  // Keys come from Settings → API Keys only — no per-page key field.
  useEffect(() => {
    setMissingKey(false);

    // Short-circuit if the provider needs a key and no key is saved.
    const apiKeys = loadApiKeys();
    const key = apiKeys[provider as keyof typeof apiKeys] || undefined;
    const providerInfo = providers.find((p) => p.id === provider);
    if (providerInfo?.requires_key && !key) {
      setVoices([]);
      setVoiceId('');
      setMissingKey(true);
      setLoadingVoices(false);
      return;
    }

    setLoadingVoices(true);
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
      .catch((err: unknown) => {
        setVoices([]);
        const msg = err instanceof Error ? err.message : String(err);
        // Even with a saved key the BE might reject it (expired/wrong scope).
        // Treat any "API key" error as a missing-key prompt; other failures
        // we currently surface only as an empty list (rare in practice).
        if (/api[_ ]key/i.test(msg)) {
          setMissingKey(true);
        }
      })
      .finally(() => setLoadingVoices(false));
  }, [provider, language, providers]);

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

  // ── generate ───────────────────────────────────────────────────────────────
  const handleGenerate = async () => {
    if (!srtFile) return;
    setGenerating(true);
    setGenError('');
    setProgress({ pct: 0, message: 'Submitting…' });
    setActiveTaskId(null);
    setCancelling(false);

    // close any previous SSE stream
    esRef.current?.close();

    try {
      const apiKeys = loadApiKeys();
      const llmPrefs = loadLLMPrefs();
      const effectiveApiKey =
        apiKeys[provider as keyof typeof apiKeys] || undefined;

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
      setActiveTaskId(resp.task_id);

      // subscribe to SSE
      const es = subscribeSSE(resp.task_id, (eventType, data) => {
        if (eventType === 'progress') {
          setProgress({
            pct: Math.round((typeof data.progress === 'number' ? data.progress : 0) * 100),
            message: typeof data.message === 'string' ? data.message : '',
          });
        } else if (eventType === 'complete') {
          setGenerating(false);
          setProgress({ pct: 100, message: 'Done!' });
          setActiveTaskId(null);
          es.close();
          void refreshRecent();
        } else if (eventType === 'error') {
          setGenerating(false);
          setGenError(typeof data.message === 'string' ? data.message : 'Generation failed');
          setActiveTaskId(null);
          es.close();
        } else if (eventType === 'cancelled') {
          setGenerating(false);
          setCancelling(false);
          setProgress({ pct: 0, message: 'Cancelled' });
          setActiveTaskId(null);
          es.close();
        }
      });
      esRef.current = es;
    } catch (err) {
      setGenerating(false);
      setGenError(err instanceof Error ? err.message : 'Unknown error');
      setActiveTaskId(null);
    }
  };

  // ── stop ───────────────────────────────────────────────────────────────────
  const handleStop = async () => {
    if (!activeTaskId || cancelling) return;
    setCancelling(true);
    try {
      await cancelTask(activeTaskId);
      // The SSE 'cancelled' event will flip generating=false; if the BE
      // is unreachable, snap the UI back ourselves.
    } catch (err) {
      setGenerating(false);
      setCancelling(false);
      setGenError(err instanceof Error ? err.message : 'Stop failed');
    }
  };

  // ── delete ─────────────────────────────────────────────────────────────────
  const handleDelete = async (uuid: string) => {
    try {
      await deleteStandaloneDub(uuid);
      await refreshRecent();
    } catch (e) {
      console.warn('[DubStudio] delete failed', e);
    }
  };

  // ── file input ref ─────────────────────────────────────────────────────────
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── render ─────────────────────────────────────────────────────────────────
  const selectedProvider = providers.find((p) => p.id === provider);

  const selectClass =
    'w-full bg-surface-container-highest border border-outline-variant/30 text-xs text-on-surface py-2 px-3 rounded focus:outline-none focus:border-primary';
  const labelClass = 'block text-[10px] text-zinc-500 uppercase tracking-tighter font-bold mb-1.5';

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 space-y-5">
        {/* heading */}
        <div>
          <h1 className="text-xl font-semibold text-on-surface">Dub Studio</h1>
          <p className="text-xs text-on-surface-variant mt-1">
            Convert any SRT subtitle file into a dubbed audio track. No video required.
          </p>
        </div>

        {/* form card */}
        <div className="bg-surface-container-low rounded-xl border border-outline-variant/10 p-5 space-y-4">
          {/* SRT file picker */}
          <div>
            <label className={labelClass}>SRT file</label>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="px-3 py-2 rounded-md text-xs font-medium bg-surface-container-highest border border-outline-variant/30 text-on-surface hover:bg-surface-container-high transition-colors flex items-center gap-1.5"
              >
                <span className="material-symbols-outlined text-sm">upload_file</span>
                {srtFile ? 'Change file' : 'Choose SRT file…'}
              </button>
              {srtFile && (
                <span className="inline-flex items-center gap-1.5 px-2 py-1 bg-primary/10 text-primary text-[11px] rounded font-mono truncate max-w-xs">
                  <span className="material-symbols-outlined text-xs">description</span>
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

          {/* Provider + Language */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>TTS provider</label>
              <select
                className={selectClass}
                value={provider}
                onChange={(e) => handleSetProvider(e.target.value)}
              >
                {providers.length === 0 && <option value={provider}>{provider}</option>}
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.free ? ' (free)' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelClass}>Language</label>
              <select
                className={selectClass}
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
            <label className={labelClass}>Voice</label>
            {loadingVoices ? (
              <div className="text-xs text-on-surface-variant italic px-3 py-2 bg-surface-container-highest border border-outline-variant/30 rounded">
                Loading voices…
              </div>
            ) : (
              <select
                className={selectClass}
                value={voiceId}
                onChange={(e) => handleSetVoiceId(e.target.value)}
                disabled={voices.length === 0}
              >
                {voices.length === 0 && <option value="">— no voices available —</option>}
                {voices.map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.friendly_name} ({v.gender})
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Missing-key warning — when the selected provider needs a key and
              none is saved in Settings → API Keys. The user can't enter it
              here; they have to open Settings. */}
          {missingKey && (
            <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg bg-amber-500/10 border border-amber-400/20">
              <span className="material-symbols-outlined text-sm text-amber-300 mt-0.5">
                warning
              </span>
              <div className="flex-1 text-xs text-amber-100">
                <strong>{selectedProvider?.name ?? provider}</strong> needs an API key. Save one in
                Settings → API Keys to load voices.
              </div>
              <Link
                to="/settings"
                className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium bg-amber-400/20 text-amber-100 hover:bg-amber-400/30 transition-colors"
              >
                <span className="material-symbols-outlined text-sm">settings</span>
                Open Settings
              </Link>
            </div>
          )}

          {/* Playback speed */}
          <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-container-highest border border-outline-variant/20">
            <span className="material-symbols-outlined text-sm text-on-surface-variant">speed</span>
            <label className="text-xs text-on-surface-variant flex-1">Playback speed</label>
            <input
              type="range"
              min={0.5}
              max={2.0}
              step={0.05}
              value={playbackSpeed}
              onChange={(e) => handleSetPlaybackSpeed(parseFloat(e.target.value))}
              className="flex-[2] accent-primary"
            />
            <span className="w-12 text-right text-xs font-mono text-on-surface">
              {playbackSpeed.toFixed(2)}×
            </span>
          </div>

          {/* Shorten toggle */}
          <label className="flex items-start gap-2.5 cursor-pointer px-3 py-2 rounded-lg bg-surface-container-highest border border-outline-variant/20">
            <input
              type="checkbox"
              checked={enableShortening}
              onChange={(e) => handleSetEnableShortening(e.target.checked)}
              className="mt-0.5 accent-primary"
            />
            <div className="flex-1">
              <div className="text-xs font-medium text-on-surface">Shorten dub to fit timeline</div>
              <div className="text-[10px] text-on-surface-variant mt-0.5 leading-snug">
                Uses the LLM to compress text when a sentence would overrun. Uncheck to keep the
                original text — clips may overrun.
              </div>
            </div>
          </label>

          {/* Generate / Stop button — same row, button swaps based on state */}
          {generating ? (
            <button
              type="button"
              onClick={() => void handleStop()}
              disabled={!activeTaskId || cancelling}
              aria-label="Stop dub generation"
              className="w-full py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 bg-red-500/15 border border-red-500/30 text-red-300 hover:bg-red-500/25 active:scale-95 disabled:opacity-50 transition-all"
            >
              <span className="material-symbols-outlined text-sm">{cancelling ? 'progress_activity' : 'stop_circle'}</span>
              {cancelling ? 'Stopping…' : `Stop · ${progress.message || 'generating'}`}
            </button>
          ) : (
            <button
              type="button"
              disabled={!srtFile || !voiceId}
              onClick={() => void handleGenerate()}
              aria-label="Generate dub"
              className={`w-full py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 transition-all ${
                !srtFile || !voiceId
                  ? 'bg-surface-container-highest text-on-surface-variant cursor-not-allowed opacity-50'
                  : 'bg-primary text-on-primary-fixed hover:brightness-110 active:scale-95'
              }`}
            >
              <span className="material-symbols-outlined text-sm">record_voice_over</span>
              Generate dub
            </button>
          )}

          {/* Progress bar */}
          {generating && (
            <div className="space-y-1.5">
              <div className="flex justify-between items-center">
                <span className="text-[10px] font-mono text-zinc-500 uppercase">{progress.message}</span>
                <span className="text-xs font-bold font-mono text-primary">{progress.pct}%</span>
              </div>
              <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-primary h-full transition-all duration-500 shadow-[0_0_8px_rgba(208,188,255,0.4)]"
                  style={{ width: `${progress.pct}%` }}
                />
              </div>
            </div>
          )}

          {/* Error */}
          {genError && (
            <div className="text-xs text-red-400 px-3 py-2 rounded bg-red-500/10 border border-red-500/20">
              {genError}
            </div>
          )}
        </div>

        {/* recent dubs */}
        <div className="bg-surface-container-low rounded-xl border border-outline-variant/10 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">
              Recent dubs ({recentDubs.length})
            </label>
          </div>

          {loadingRecent ? (
            <p className="text-xs text-on-surface-variant italic">Loading…</p>
          ) : recentDubs.length === 0 ? (
            <div className="text-center text-xs text-on-surface-variant py-6 bg-surface-container-lowest rounded-lg">
              No dubs yet. Generate one above!
            </div>
          ) : (
            <div className="space-y-1">
              {recentDubs.map((dub) => {
                const isPlaying = playingUuid === dub.uuid;
                const audioUrl = getStandaloneDubUrl(dub.uuid);
                return (
                  <div
                    key={dub.uuid}
                    className="flex items-center gap-2 px-3 py-2 bg-surface-container-lowest rounded-lg group"
                  >
                    <button
                      type="button"
                      onClick={() => setPlayingUuid(isPlaying ? null : dub.uuid)}
                      className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                        isPlaying
                          ? 'bg-primary text-on-primary-fixed'
                          : 'bg-surface-container-high text-on-surface-variant hover:bg-primary/20'
                      }`}
                    >
                      <span className="material-symbols-outlined text-sm">
                        {isPlaying ? 'stop' : 'play_arrow'}
                      </span>
                    </button>
                    <div className="flex-1 min-w-0 flex items-center gap-1.5">
                      <span
                        className="shrink-0 bg-primary/15 text-primary text-[9px] font-semibold px-1.5 py-0.5 rounded truncate max-w-[160px]"
                        title={dub.original_filename}
                      >
                        {dub.original_filename}
                      </span>
                      <span className="text-[11px] font-semibold text-on-surface truncate">
                        {dub.voice}
                      </span>
                      <span className="text-[9px] text-zinc-500 shrink-0">
                        {dub.provider} · {dub.language.toUpperCase()} · {fmtDuration(dub.duration_seconds)} · {fmtSize(dub.file_size_bytes)}
                      </span>
                    </div>
                    <span className="text-[9px] font-mono text-zinc-600 shrink-0">{fmtDate(dub.created_at)}</span>
                    <a
                      href={audioUrl}
                      download={`${dub.original_filename.replace(/\.srt$/i, '')}_dub.wav`}
                      className="p-1 rounded hover:bg-primary/20 text-zinc-600 hover:text-primary transition-all"
                      title="Download dub"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <span className="material-symbols-outlined text-sm">download</span>
                    </a>
                    <button
                      type="button"
                      onClick={() => void handleDelete(dub.uuid)}
                      className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/20 text-zinc-600 hover:text-red-400 transition-all"
                      title="Delete dub"
                      aria-label="Delete"
                    >
                      <span className="material-symbols-outlined text-sm">delete</span>
                    </button>
                    {isPlaying && (
                      <audio
                        autoPlay
                        src={audioUrl}
                        onEnded={() => setPlayingUuid(null)}
                        style={{ display: 'none' }}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
