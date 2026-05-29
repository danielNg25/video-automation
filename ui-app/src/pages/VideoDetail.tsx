import { useState, useEffect, useCallback } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { EditorTab } from './videoDetail/EditorTab';
import { TranslateTab } from './videoDetail/TranslateTab';
import { DubTab } from './videoDetail/DubTab';
import { ExportTab } from './videoDetail/ExportTab';
import {
  getVideo, postTranslate, postTTS, postExport, deleteExport,
  subscribeSSE, getProfiles, getTTSProviders, getTTSVoices,
  getTTSList,
} from '../api/client';
import type { TTSAudioEntry } from '../api/client';
import type {
  VideoMetadata, TranslationProfileSummary,
  TTSProviderInfo, VoiceInfo,
} from '../api/types';
import { loadApiKeys, loadLLMPrefs, storageGet, storageSet } from '../utils/storage';
import { useVersions } from '../hooks/useVersions';

type Tab = 'editor' | 'translate' | 'dub' | 'export';

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

function VideoDetailPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get('tab') as Tab) || 'editor';
  const setActiveTab = (tab: Tab) => setSearchParams((p) => { p.set('tab', tab); return p; }, { replace: true });

  // Video state
  const [videoMeta, setVideoMeta] = useState<VideoMetadata | null>(null);
  const [error, setError] = useState('');

  // Translation state
  const [profiles, setProfiles] = useState<TranslationProfileSummary[]>([]);
  const [selectedProfile, setSelectedProfile] = useState('');
  const [isTranslating, setIsTranslating] = useState(false);
  const [translateMessage, setTranslateMessage] = useState('');
  const [translateProgress, setTranslateProgress] = useState(0);
  const [savedPrefs] = useState(loadLLMPrefs);
  const [llmBackend, setLlmBackend] = useState(savedPrefs.backend);
  const [llmModel, setLlmModel] = useState(savedPrefs.model);
  const [llmApiKey, setLlmApiKey] = useState('');
  const [llmBaseUrl, setLlmBaseUrl] = useState('');

  // TTS state
  const [ttsProviders, setTtsProviders] = useState<TTSProviderInfo[]>([]);
  const [selectedTtsProvider, setSelectedTtsProvider] = useState(
    () => storageGet('tts_selected_provider') || 'google'
  );
  const [ttsVoices, setTtsVoices] = useState<VoiceInfo[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState(() => {
    const provider = storageGet('tts_selected_provider') || 'google';
    return storageGet(`tts_voice_id_${provider}`) || storageGet('tts_voice_id') || '';
  });
  const [voiceIdInput, setVoiceIdInput] = useState(() => {
    const provider = storageGet('tts_selected_provider') || 'google';
    return storageGet(`tts_voice_id_${provider}`) || storageGet('tts_voice_id') || '';
  });
  const [voiceIdSaved, setVoiceIdSaved] = useState(false);
  const [ttsApiKey, setTtsApiKey] = useState('');
  const [ttsLanguage, setTtsLanguage] = useState(
    () => storageGet('tts_language') || 'vi'
  );
  const [playbackSpeed, setPlaybackSpeed] = useState(() => {
    const saved = parseFloat(storageGet('tts_playback_speed') || '');
    return Number.isFinite(saved) && saved >= 1.0 && saved <= 2.0 ? saved : 1.5;
  });
  const [underlayDb, setUnderlayDb] = useState(() => {
    const saved = parseFloat(storageGet('tts_underlay_db') || '');
    return Number.isFinite(saved) && saved >= -24 && saved <= 0 ? saved : -18;
  });
  const [enableShortening, setEnableShortening] = useState<boolean>(() => {
    const stored = storageGet('tts_enable_shortening');
    return stored === null ? true : stored === 'true';
  });
  const [useDirectVoice, setUseDirectVoice] = useState(false);
  const [isGeneratingTts, setIsGeneratingTts] = useState(false);
  const [ttsProgress, setTtsProgress] = useState({ pct: 0, message: '' });
  const [ttsGenerated, setTtsGenerated] = useState(false);
  const [ttsError, setTtsError] = useState('');
  const [ttsList, setTtsList] = useState<TTSAudioEntry[]>([]);

  // Editor active language — lifted here so useVersions tracks the language
  // the user is actually editing, not the TTS dub language.
  const [activeLang, setActiveLang] = useState('');

  // Version state (shared across Editor + Dub tabs) — scoped to the language
  // the user is editing so VersionPanel always shows the right snapshots.
  const { versions, createSnapshot, rename, remove } = useVersions(videoId, activeLang);
  const [selectedVersion, setSelectedVersion] = useState('draft');

  // Export state
  const [isExporting, setIsExporting] = useState(false);
  const [exportProgress, setExportProgress] = useState<{ pct: number; message: string }>({ pct: 0, message: '' });
  const [exportDone, setExportDone] = useState(false);
  const [exportError, setExportError] = useState('');
  const [exportTimestamp, setExportTimestamp] = useState(0);

  // Load API key from localStorage when backend changes
  useEffect(() => {
    const keys = loadApiKeys();
    const keyMap: Record<string, string> = { anthropic: keys.anthropic, openai: keys.openai, deepseek: keys.deepseek };
    setLlmApiKey(keyMap[llmBackend] || '');
    if (llmBackend === 'deepseek') setLlmBaseUrl('https://api.deepseek.com');
    else setLlmBaseUrl('');
  }, [llmBackend]);

  // Load TTS API key from localStorage when provider changes
  useEffect(() => {
    const keys = loadApiKeys();
    setTtsApiKey(keys[selectedTtsProvider] || '');
  }, [selectedTtsProvider]);

  const loadVoicesForProvider = useCallback(async (provider: string, apiKey?: string, language?: string) => {
    try {
      const voices = await getTTSVoices(language || ttsLanguage, provider, apiKey);
      setTtsVoices(voices);
      if (voices.length > 0) {
        // Honor the saved voice ID if it's still valid for this provider; else
        // fall back to the first voice in the list.
        const saved = storageGet(`tts_voice_id_${provider}`) || '';
        const isValid = !!saved && voices.some(v => v.name === saved);
        const picked = isValid ? saved : voices[0].name;
        setSelectedVoiceId(picked);
        if (!isValid && saved) {
          // Saved value was stale — clear it so the dropdown is authoritative.
          storageSet(`tts_voice_id_${provider}`, '');
        }
      }
    } catch {
      setTtsVoices([]);
    }
  }, [ttsLanguage]);

  // One-time migration of legacy tts_voice_id key to per-provider keys.
  useEffect(() => {
    migrateLegacyVoiceId(selectedTtsProvider);
    // Persist the current selection so future mounts can resolve per-provider keys.
    storageSet('tts_selected_provider', selectedTtsProvider);
  }, []); // run once on mount

  useEffect(() => {
    storageSet('tts_enable_shortening', String(enableShortening));
  }, [enableShortening]);

  // Auto-fetch the voice list whenever the relevant inputs change. Without
  // this, opening DubTab on a fresh mount shows "Loading voices..." forever
  // because nothing else triggers loadVoicesForProvider until the user
  // manually changes a picker. Fires on mount with the default provider, on
  // provider switch, when the per-provider API key finishes loading, and on
  // language change (the closure captures ttsLanguage).
  useEffect(() => {
    if (!selectedTtsProvider) return;
    loadVoicesForProvider(selectedTtsProvider, ttsApiKey || undefined);
  }, [selectedTtsProvider, ttsApiKey, loadVoicesForProvider]);

  // Load video + supporting data on mount
  useEffect(() => {
    if (!videoId) return;

    const loadAll = async () => {
      try {
        const video = await getVideo(videoId);
        setVideoMeta(video);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load video');
      }

      try {
        const p = await getProfiles();
        setProfiles(p);
        if (p.length > 0) setSelectedProfile(p[0].name);
      } catch { /* profiles not available */ }

      try {
        const provs = await getTTSProviders();
        setTtsProviders(provs);
      } catch { /* TTS not available */ }

      // Load existing TTS audio files
      try {
        const list = await getTTSList(videoId);
        setTtsList(list);
        if (list.length > 0) setTtsGenerated(true);
      } catch { /* no TTS audio yet */ }
    };

    loadAll();
  }, [videoId]);

  // ── Handlers ──

  const refreshVideoMeta = useCallback(async () => {
    if (!videoId) return;
    try {
      const updated = await getVideo(videoId);
      setVideoMeta(updated);
    } catch {
      // ignore — fresh fetch failed, banner will refresh on next mount
    }
  }, [videoId]);

  const handleTranslate = async () => {
    if (!videoMeta || !selectedProfile) return;
    setError('');
    setIsTranslating(true);
    setTranslateProgress(0);
    setTranslateMessage('Loading translation profile...');

    const sourceLang = videoMeta.srt_languages.includes('zh')
      ? 'zh'
      : videoMeta.srt_languages.includes('en')
        ? 'en'
        : videoMeta.srt_languages[0] || 'zh';

    try {
      const overrides: { backend?: string; model?: string; api_key?: string; base_url?: string } = {};
      overrides.backend = llmBackend === 'deepseek' ? 'openai' : llmBackend;
      if (llmModel) overrides.model = llmModel;
      if (llmApiKey) overrides.api_key = llmApiKey;
      if (llmBaseUrl) overrides.base_url = llmBaseUrl;
      const { task_id } = await postTranslate(videoMeta.video_id, selectedProfile, sourceLang, overrides);
      const es = subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') {
          setTranslateProgress((data.progress as number) * 100);
          setTranslateMessage(data.message as string);
        } else if (eventType === 'complete') {
          setIsTranslating(false);
          setTranslateProgress(100);
          setTranslateMessage('Translation complete');
          getVideo(videoMeta.video_id).then((updated) => setVideoMeta(updated));
          es.close();
        } else if (eventType === 'error') {
          setIsTranslating(false);
          setError(data.message as string);
          es.close();
        }
      });
    } catch (e) {
      setIsTranslating(false);
      setError(e instanceof Error ? e.message : 'Translation failed');
    }
  };

  const handleGenerateTts = async () => {
    if (!videoMeta) return;
    setIsGeneratingTts(true);
    setTtsError('');
    setTtsProgress({ pct: 0, message: 'Starting TTS generation...' });

    try {
      const voiceForRequest = selectedTtsProvider === 'elevenlabs'
        ? voiceIdInput
        : selectedVoiceId;
      if (!voiceForRequest) {
        setIsGeneratingTts(false);
        setTtsError('Pick a voice first.');
        return;
      }
      const { task_id } = await postTTS(
        videoMeta.video_id,
        ttsLanguage,
        selectedTtsProvider,
        voiceForRequest,
        selectedVersion,
        enableShortening,
        ttsApiKey || undefined,
        llmApiKey || undefined,
        llmBackend || undefined,
        playbackSpeed,
        underlayDb,
      );
      const es = subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') {
          setTtsProgress({
            pct: Math.round((data.progress as number) * 100),
            message: data.message as string,
          });
        } else if (eventType === 'complete') {
          setIsGeneratingTts(false);
          setTtsGenerated(true);
          setTtsProgress({ pct: 100, message: 'TTS generation complete' });
          // Refresh TTS list to show new file
          if (videoMeta) getTTSList(videoMeta.video_id).then(setTtsList).catch(() => {});
          es.close();
        } else if (eventType === 'error') {
          setIsGeneratingTts(false);
          setTtsError(data.message as string);
          es.close();
        }
      });
    } catch (e) {
      setIsGeneratingTts(false);
      setTtsError(e instanceof Error ? e.message : 'TTS generation failed');
    }
  };

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

  const handleExport = async (params: {
    subtitleLanguage: string | null;
    ttsFile: string | null;
    videoVolume: number;
    ttsVolume: number;
  }) => {
    if (!videoMeta) return;
    setIsExporting(true);
    setExportError('');
    setExportDone(false);
    setExportProgress({ pct: 0, message: 'Starting...' });
    try {
      await deleteExport(videoMeta.video_id).catch(() => {});
      const { task_id } = await postExport(
        videoMeta.video_id,
        params.subtitleLanguage,
        params.ttsFile,
        params.videoVolume,
        params.ttsVolume,
      );
      const es = subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') {
          setExportProgress({
            pct: Math.round((data.progress as number) * 100),
            message: data.message as string,
          });
        } else if (eventType === 'complete') {
          setIsExporting(false);
          setExportDone(true);
          setExportTimestamp(Date.now());
          setExportProgress({ pct: 100, message: 'Export complete' });
          getVideo(videoMeta.video_id).then(setVideoMeta).catch(() => {});
          es.close();
        } else if (eventType === 'error') {
          setIsExporting(false);
          setExportError(data.message as string);
          es.close();
        }
      });
    } catch (e) {
      setIsExporting(false);
      setExportError(e instanceof Error ? e.message : 'Export failed');
    }
  };


  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb={videoMeta?.title || 'Video Detail'} />

      <div className="px-6 pt-4">
        <div className="flex gap-1 bg-surface-container-lowest p-1 rounded-md w-fit">
          {(['editor', 'translate', 'dub', 'export'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setActiveTab(t)}
              className={`px-4 py-1.5 text-xs font-bold uppercase tracking-tighter rounded-sm ${
                activeTab === t ? 'bg-surface-container-high text-primary' : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <section className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Error Banner */}
        {error && (
          <div className="bg-error/10 border border-error/30 text-error text-xs p-3 rounded-lg flex items-center gap-2">
            <span className="material-symbols-outlined text-sm">error</span>
            {error}
            <button onClick={() => setError('')} className="ml-auto">
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </div>
        )}

        {activeTab === 'editor' && videoMeta && (
          <EditorTab
            videoId={videoMeta.video_id}
            initialVideo={videoMeta}
            onSyncComplete={refreshVideoMeta}
            versions={versions}
            onCreateSnapshot={createSnapshot}
            onRenameVersion={rename}
            onDeleteVersion={remove}
            activeLang={activeLang}
            onActiveLangChange={setActiveLang}
          />
        )}

        {activeTab === 'translate' && videoMeta && (
          <TranslateTab
            profiles={profiles}
            selectedProfile={selectedProfile}
            onChangeProfile={setSelectedProfile}
            llmBackend={llmBackend}
            onChangeLlmBackend={setLlmBackend}
            llmModel={llmModel}
            onChangeLlmModel={setLlmModel}
            llmApiKey={llmApiKey}
            onChangeLlmApiKey={setLlmApiKey}
            llmBaseUrl={llmBaseUrl}
            onChangeLlmBaseUrl={setLlmBaseUrl}
            isTranslating={isTranslating}
            translateMessage={translateMessage}
            translateProgress={translateProgress}
            onTranslate={handleTranslate}
          />
        )}

        {activeTab === 'dub' && videoMeta && (
          <DubTab
            videoId={videoMeta.video_id}
            versions={versions}
            selectedVersion={selectedVersion}
            onVersionChange={setSelectedVersion}
            ttsProviders={ttsProviders}
            selectedTtsProvider={selectedTtsProvider}
            onChangeTtsProvider={handleTtsProviderChange}
            ttsVoices={ttsVoices}
            selectedVoiceId={selectedVoiceId}
            onChangeSelectedVoiceId={(v) => { setSelectedVoiceId(v); setTtsGenerated(false); }}
            voiceIdInput={voiceIdInput}
            onChangeVoiceIdInput={(v) => { setVoiceIdInput(v); setVoiceIdSaved(false); }}
            voiceIdSaved={voiceIdSaved}
            onSaveVoiceId={() => {
              storageSet(`tts_voice_id_${selectedTtsProvider}`, voiceIdInput);
              setSelectedVoiceId(voiceIdInput);
              setVoiceIdSaved(true);
              setTtsGenerated(false);
              setTimeout(() => setVoiceIdSaved(false), 2000);
            }}
            ttsApiKey={ttsApiKey}
            onChangeTtsApiKey={setTtsApiKey}
            ttsLanguage={ttsLanguage}
            onChangeTtsLanguage={(lang) => {
              setTtsLanguage(lang);
              setTtsGenerated(false);
              setTtsVoices([]);
              loadVoicesForProvider(selectedTtsProvider, ttsApiKey || undefined, lang);
            }}
            availableTtsLanguages={(videoMeta.srt_languages || []).filter((l) => l !== 'zh')}
            playbackSpeed={playbackSpeed}
            onChangePlaybackSpeed={setPlaybackSpeed}
            underlayDb={underlayDb}
            onChangeUnderlayDb={setUnderlayDb}
            useDirectVoice={useDirectVoice}
            onChangeUseDirectVoice={setUseDirectVoice}
            isGeneratingTts={isGeneratingTts}
            ttsProgress={ttsProgress}
            ttsGenerated={ttsGenerated}
            ttsError={ttsError}
            ttsList={ttsList}
            onReloadTtsList={async () => {
              if (!videoMeta) return;
              try {
                const list = await getTTSList(videoMeta.video_id);
                setTtsList(list);
              } catch { /* ignore */ }
            }}
            onGenerate={handleGenerateTts}
            llmBackend={llmBackend}
            llmApiKey={llmApiKey}
            enableShortening={enableShortening}
            onChangeEnableShortening={setEnableShortening}
          />
        )}

        {activeTab === 'export' && videoMeta && (
          <ExportTab
            video={videoMeta}
            ttsList={ttsList}
            onExport={handleExport}
            isExporting={isExporting}
            exportProgress={exportProgress}
            exportDone={exportDone}
            exportError={exportError}
            exportTimestamp={exportTimestamp}
            onExportTimestampSync={setExportTimestamp}
            onExportDoneSync={setExportDone}
          />
        )}
      </section>
    </div>
  );
}

export default VideoDetailPage;
