import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { TTSPreview } from '../components/TTSPreview';
import { SubtitleEditorPanel } from '../components/SubtitleEditorPanel';
import { OverviewTab } from './videoDetail/OverviewTab';
import { TranslateTab } from './videoDetail/TranslateTab';
import {
  getVideo, getSrt, postTranscribe, postTranslate, postTTS,
  subscribeSSE, getProfiles, getTTSProfiles, getTTSProviders, getTTSVoices,
  getTTSAudioUrl, getTTSList, deleteTTSAudio,
  patchVideoTitle, postTTSPreview,
} from '../api/client';
import type { TTSAudioEntry } from '../api/client';
import type {
  VideoMetadata, SubtitleSegment, TranslationProfileSummary,
  VoiceProfileConfig, TTSProviderInfo, VoiceInfo,
} from '../api/types';
import { loadApiKeys, loadLLMPrefs, storageGet, storageSet } from '../utils/storage';

const PLATFORM_INFO: Record<string, { label: string; subLangLabel: string; constraint: string }> = {
  tiktok: { label: 'TikTok', subLangLabel: 'Vietnamese', constraint: '9:16 / 10min / 4GB' },
  youtube: { label: 'YouTube', subLangLabel: 'English', constraint: '9:16 / Shorts / 256GB' },
  facebook: { label: 'Facebook', subLangLabel: 'Vietnamese', constraint: '9:16 / 15min / 4GB' },
  x: { label: 'X / Twitter', subLangLabel: 'English', constraint: '9:16 / 2:20 / 512MB' },
};

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
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  type Tab = 'overview' | 'translate' | 'dub' | 'export';
  const activeTab = (searchParams.get('tab') as Tab) || 'overview';
  const setActiveTab = (tab: Tab) => setSearchParams((p) => { p.set('tab', tab); return p; }, { replace: true });

  // Video state
  const [videoMeta, setVideoMeta] = useState<VideoMetadata | null>(null);
  const [error, setError] = useState('');
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');

  // SRT state
  const [srtSegments, setSrtSegments] = useState<SubtitleSegment[]>([]);
  const [previewLanguage, setPreviewLanguage] = useState('');

  // Transcribe state
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcribeMessage, setTranscribeMessage] = useState('');

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
  const [selectedTtsProvider, setSelectedTtsProvider] = useState('elevenlabs');
  const [ttsProfiles, setTtsProfiles] = useState<Record<string, VoiceProfileConfig>>({});
  const [selectedTtsProfile, setSelectedTtsProfile] = useState('female-vi-natural');
  const [ttsVoices, setTtsVoices] = useState<VoiceInfo[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState(() => {
    const provider = storageGet('tts_selected_provider') || 'elevenlabs';
    return storageGet(`tts_voice_id_${provider}`) || storageGet('tts_voice_id') || '';
  });
  const [voiceIdInput, setVoiceIdInput] = useState(() => {
    const provider = storageGet('tts_selected_provider') || 'elevenlabs';
    return storageGet(`tts_voice_id_${provider}`) || storageGet('tts_voice_id') || '';
  });
  const [voiceIdSaved, setVoiceIdSaved] = useState(false);
  const [ttsApiKey, setTtsApiKey] = useState('');
  const [ttsLanguage, setTtsLanguage] = useState('vi');
  const [playbackSpeed, setPlaybackSpeed] = useState(() => {
    const saved = parseFloat(storageGet('tts_playback_speed') || '');
    return Number.isFinite(saved) && saved >= 1.0 && saved <= 2.0 ? saved : 1.5;
  });
  const [underlayDb, setUnderlayDb] = useState(() => {
    const saved = parseFloat(storageGet('tts_underlay_db') || '');
    return Number.isFinite(saved) && saved >= -24 && saved <= 0 ? saved : -18;
  });
  const [useDirectVoice, setUseDirectVoice] = useState(false);
  const [isGeneratingTts, setIsGeneratingTts] = useState(false);
  const [ttsProgress, setTtsProgress] = useState({ pct: 0, message: '' });
  const [ttsGenerated, setTtsGenerated] = useState(false);
  const [ttsError, setTtsError] = useState('');
  const [ttsList, setTtsList] = useState<TTSAudioEntry[]>([]);
  const [playingTts, setPlayingTts] = useState<string | null>(null);

  // Export state (managed by SubtitleEditorPanel, just need previewLanguage for pass-through)

  // Panel collapse state — editor open by default
  const [openPanels, setOpenPanels] = useState<Set<string>>(new Set(['editor']));
  const togglePanel = useCallback((key: string) => {
    setOpenPanels(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

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

  const loadSrt = useCallback(async (vid: string, lang: string) => {
    try {
      const srt = await getSrt(vid, lang);
      setSrtSegments(srt.segments);
      setPreviewLanguage(lang);
    } catch {
      setSrtSegments([]);
    }
  }, []);

  const handleEditorReload = useCallback(async () => {
    if (!videoId) return;
    try {
      const video = await getVideo(videoId);
      setVideoMeta(video);
      if (video.srt_languages.length > 0 && !previewLanguage) {
        setPreviewLanguage(video.srt_languages[0]);
      }
    } catch { /* ignore */ }
    try {
      const list = await getTTSList(videoId);
      setTtsList(list);
    } catch { /* ignore */ }
  }, [videoId, previewLanguage]);

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

  // Load video + supporting data on mount
  useEffect(() => {
    if (!videoId) return;

    const loadAll = async () => {
      try {
        const video = await getVideo(videoId);
        setVideoMeta(video);
        if (video.srt_languages.length > 0) {
          loadSrt(videoId, video.srt_languages[0]);
          setPreviewLanguage(video.srt_languages[0]);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load video');
      }

      try {
        const p = await getProfiles();
        setProfiles(p);
        if (p.length > 0) setSelectedProfile(p[0].name);
      } catch { /* profiles not available */ }

      try {
        const [profs, provs] = await Promise.all([getTTSProfiles(), getTTSProviders()]);
        setTtsProfiles(profs);
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
  }, [videoId, loadSrt]);

  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  // ── Handlers ──

  const handleTranscribe = async () => {
    if (!videoMeta) return;
    setError('');
    setIsTranscribing(true);
    setTranscribeMessage('Initializing OCR engine...');
    setSrtSegments([]);

    try {
      const { task_id } = await postTranscribe(videoMeta.video_id, 'zh', 'transcribe');
      const es = subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') {
          setTranscribeMessage(data.message as string);
        } else if (eventType === 'complete') {
          setIsTranscribing(false);
          setTranscribeMessage('Transcription complete');
          const srtLang = (data.language as string) || 'zh';
          loadSrt(videoMeta.video_id, srtLang);
          getVideo(videoMeta.video_id).then((updated) => setVideoMeta(updated));
          es.close();
        } else if (eventType === 'error') {
          setIsTranscribing(false);
          setError(data.message as string);
          es.close();
        }
      });
    } catch (e) {
      setIsTranscribing(false);
      setError(e instanceof Error ? e.message : 'Transcription failed');
    }
  };

  const handleSaveTitle = async () => {
    if (!videoMeta || !titleDraft.trim()) return;
    try {
      const updated = await patchVideoTitle(videoMeta.video_id, titleDraft.trim());
      setVideoMeta(updated);
      setEditingTitle(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update title');
    }
  };

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
          const targetLang = data.target_language as string;
          getVideo(videoMeta.video_id).then((updated) => {
            setVideoMeta(updated);
            if (targetLang) loadSrt(videoMeta.video_id, targetLang);
          });
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
      const { task_id } = await postTTS(
        videoMeta.video_id,
        ttsLanguage,
        selectedTtsProfile,
        selectedTtsProvider,
        selectedVoiceId || undefined,
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

  const handleTtsProfileChange = (profileName: string) => {
    setSelectedTtsProfile(profileName);
    const profile = ttsProfiles[profileName];
    if (profile) {
      setTtsLanguage(profile.language);
      setSelectedTtsProvider(profile.provider);
    }
    setTtsGenerated(false);
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


  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb={videoMeta?.title || 'Video Detail'} />

      <div className="px-6 pt-4">
        <div className="flex gap-1 bg-surface-container-lowest p-1 rounded-md w-fit">
          {(['overview', 'translate', 'dub', 'export'] as const).map((t) => (
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

        {activeTab === 'overview' && videoMeta && (
          <OverviewTab
            video={videoMeta}
            editingTitle={editingTitle}
            titleDraft={titleDraft}
            isTranscribing={isTranscribing}
            transcribeMessage={transcribeMessage}
            onStartTitleEdit={() => { setTitleDraft(videoMeta.title || ''); setEditingTitle(true); }}
            onChangeTitleDraft={setTitleDraft}
            onSaveTitle={handleSaveTitle}
            onCancelTitleEdit={() => setEditingTitle(false)}
            onTranscribe={handleTranscribe}
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

        {(activeTab === 'dub' || activeTab === 'export') && (
        <div className="space-y-6">
          {/* === LEGACY BODY (Tasks 7, 8 will replace these slices) === */}
          {/* Video Editor — main view */}
          {videoMeta && videoMeta.has_srt && (
            <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
              <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-lg">edit_note</span>
                  <span className="text-xs font-bold uppercase tracking-widest">Video Editor</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-[10px] font-mono text-zinc-500">
                    {videoMeta.resolution} · {videoMeta.size} · {videoMeta.codec}
                  </span>
                </div>
              </div>
              <div className="p-5">
                <SubtitleEditorPanel
                  videoId={videoMeta.video_id}
                  srtLanguages={videoMeta.srt_languages}
                  defaultLang={previewLanguage || videoMeta.srt_languages.find(l => l !== 'zh') || videoMeta.srt_languages[0]}
                  ttsList={ttsList}
                  onReload={handleEditorReload}
                />
              </div>
            </div>
          )}

            {/* TTS Dubbing Panel */}
            {videoMeta && videoMeta.has_srt && videoMeta.srt_languages.some(l => l !== 'zh') && (
              <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
                <button
                  onClick={() => togglePanel('tts')}
                  className="w-full p-4 border-b border-outline-variant/10 flex justify-between items-center hover:bg-surface-container/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-lg">record_voice_over</span>
                    <span className="text-xs font-bold uppercase tracking-widest">TTS Dubbing</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-primary bg-primary/10 px-2 py-0.5 rounded uppercase">
                      {selectedTtsProvider}
                    </span>
                    <span className={`material-symbols-outlined text-sm text-zinc-500 transition-transform ${openPanels.has('tts') ? 'rotate-180' : ''}`}>expand_more</span>
                  </div>
                </button>
                {openPanels.has('tts') && <div className="p-5 space-y-4">
                  {/* Provider + Language */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">Provider</label>
                      <select
                        value={selectedTtsProvider}
                        onChange={(e) => handleTtsProviderChange(e.target.value)}
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                      >
                        {ttsProviders.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name} {p.free ? '(Free)' : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">Language</label>
                      <select
                        value={ttsLanguage}
                        onChange={(e) => { const lang = e.target.value; setTtsLanguage(lang); setTtsGenerated(false); setTtsVoices([]); loadVoicesForProvider(selectedTtsProvider, ttsApiKey || undefined, lang); }}
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                      >
                        {videoMeta?.srt_languages.filter(l => l !== 'zh').map((lang) => (
                          <option key={lang} value={lang}>
                            {lang === 'vi' ? 'Vietnamese' : lang === 'en' ? 'English' : lang.toUpperCase()}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* API Key Warning for paid providers */}
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
                          className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary placeholder:text-zinc-600 font-mono"
                        />
                        <button
                          onClick={() => {
                            setSelectedVoiceId(voiceIdInput);
                            storageSet(`tts_voice_id_${selectedTtsProvider}`, voiceIdInput);
                            setVoiceIdSaved(true);
                            setTtsGenerated(false);
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

                  {/* Other providers: Browse voices dropdown */}
                  {selectedTtsProvider !== 'elevenlabs' && (
                    <div className="space-y-1">
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block">Voice</label>
                      <select
                        value={selectedVoiceId}
                        onChange={(e) => {
                          setSelectedVoiceId(e.target.value);
                          storageSet(`tts_voice_id_${selectedTtsProvider}`, e.target.value);
                          setTtsGenerated(false);
                        }}
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                      >
                        {ttsVoices.length === 0 && <option value="">Loading voices...</option>}
                        {ttsVoices.map((v) => (
                          <option key={v.name} value={v.name}>
                            {v.friendly_name || v.name} ({v.gender}) — {v.language}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* Dub playback speed — applied uniformly to every sentence,
                      and also applied to the preview below so the user can hear
                      the chosen speed before generating. */}
                  <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-container-highest">
                    <span className="material-symbols-outlined text-sm text-on-surface-variant">speed</span>
                    <label className="text-xs text-on-surface-variant flex-1">
                      Dub playback speed
                    </label>
                    <input
                      type="number"
                      min={1.0}
                      max={2.0}
                      step={0.1}
                      value={playbackSpeed}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value);
                        if (Number.isFinite(v) && v >= 1.0 && v <= 2.0) {
                          setPlaybackSpeed(v);
                          storageSet('tts_playback_speed', String(v));
                        }
                      }}
                      className="w-16 px-2 py-1 text-xs font-mono text-on-surface bg-surface-container-low border border-outline-variant/30 rounded focus:outline-none focus:border-primary"
                    />
                    <span className="text-[10px] text-on-surface-variant font-mono">×</span>
                  </div>

                  {/* Original-language underlay */}
                  <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-container-highest">
                    <span className="material-symbols-outlined text-sm text-on-surface-variant">graphic_eq</span>
                    <label className="text-xs text-on-surface-variant flex-1">
                      Original underlay
                    </label>
                    <select
                      value={String(underlayDb)}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value);
                        setUnderlayDb(v);
                        storageSet('tts_underlay_db', String(v));
                      }}
                      className="px-2 py-1 text-xs font-mono text-on-surface bg-surface-container-low border border-outline-variant/30 rounded focus:outline-none focus:border-primary"
                    >
                      <option value="0">Off</option>
                      <option value="-24">-24</option>
                      <option value="-18">-18</option>
                      <option value="-12">-12</option>
                      <option value="-6">-6</option>
                    </select>
                    <span className="text-[10px] text-on-surface-variant font-mono">dB</span>
                  </div>

                  {/* Voice Preview */}
                  {(() => {
                    const previewVoice = selectedVoiceId;
                    const previewProvider = selectedTtsProvider;
                    return previewVoice ? (
                      <div className="flex items-center gap-3">
                        <TTSPreview
                          voice={previewVoice}
                          provider={previewProvider}
                          speed="+0%"
                          pitch="+0Hz"
                          apiKey={ttsApiKey || undefined}
                          playbackSpeed={playbackSpeed}
                          underlayDb={underlayDb}
                          sampleText={
                            ttsLanguage === 'vi'
                              ? 'Xin chào các bạn, hôm nay chúng ta sẽ nói về một chủ đề rất thú vị.'
                              : 'Hello everyone, today we will talk about a very interesting topic.'
                          }
                        />
                        <span className="font-mono text-[9px] text-on-surface-variant truncate">
                          {previewVoice}
                        </span>
                      </div>
                    ) : null;
                  })()}

                  {/* Generate TTS Button */}
                  <button
                    disabled={isGeneratingTts}
                    onClick={handleGenerateTts}
                    className={`w-full py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 transition-all ${
                      ttsGenerated
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20'
                        : isGeneratingTts
                          ? 'bg-surface-container-highest text-on-surface-variant cursor-wait'
                          : 'bg-primary text-on-primary-fixed hover:brightness-110 active:scale-95'
                    }`}
                  >
                    {isGeneratingTts ? (
                      <>
                        <span className="material-symbols-outlined animate-spin text-sm">progress_activity</span>
                        {ttsProgress.message || 'Generating...'}
                      </>
                    ) : ttsGenerated ? (
                      <>
                        <span className="material-symbols-outlined text-sm">check_circle</span>
                        TTS Generated — Regenerate
                      </>
                    ) : (
                      <>
                        <span className="material-symbols-outlined text-sm">record_voice_over</span>
                        Generate TTS Audio
                      </>
                    )}
                  </button>

                  {/* TTS Progress */}
                  {isGeneratingTts && (
                    <div className="space-y-1.5">
                      <div className="flex justify-between items-center">
                        <span className="text-[10px] font-mono text-zinc-500 uppercase">{ttsProgress.message}</span>
                        <span className="text-xs font-bold font-mono text-primary">{ttsProgress.pct}%</span>
                      </div>
                      <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden">
                        <div
                          className="bg-primary h-full transition-all duration-500 shadow-[0_0_8px_rgba(208,188,255,0.4)]"
                          style={{ width: `${ttsProgress.pct}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* TTS Audio Library */}
                  {ttsList.length > 0 && videoMeta && (
                    <div className="space-y-2">
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">
                        Generated Dubs ({ttsList.length})
                      </label>
                      <div className="space-y-1">
                        {ttsList.map((entry) => {
                          const isPlaying = playingTts === entry.filename;
                          const audioUrl = getTTSAudioUrl(videoMeta.video_id, entry.language, entry.filename);
                          const ago = (() => {
                            const diff = (Date.now() / 1000) - entry.created_at;
                            if (diff < 60) return 'just now';
                            if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
                            if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
                            return `${Math.floor(diff / 86400)}d ago`;
                          })();
                          const sizeMb = (entry.size / 1024 / 1024).toFixed(1);
                          return (
                            <div key={entry.filename} className="flex items-center gap-2 px-3 py-2 bg-surface-container-lowest rounded-lg group">
                              <button
                                onClick={() => {
                                  if (isPlaying) {
                                    document.querySelectorAll<HTMLAudioElement>('audio.tts-player').forEach(a => { a.pause(); a.currentTime = 0; });
                                    setPlayingTts(null);
                                  } else {
                                    document.querySelectorAll<HTMLAudioElement>('audio.tts-player').forEach(a => { a.pause(); a.currentTime = 0; });
                                    setPlayingTts(entry.filename);
                                  }
                                }}
                                className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${isPlaying ? 'bg-primary text-on-primary-fixed' : 'bg-surface-container-high text-on-surface-variant hover:bg-primary/20'}`}
                              >
                                <span className="material-symbols-outlined text-sm">{isPlaying ? 'stop' : 'play_arrow'}</span>
                              </button>
                              <div className="flex-1 min-w-0">
                                <span className="text-[11px] font-semibold text-on-surface">{entry.profile}</span>
                                <span className="text-[9px] text-zinc-500 ml-2">{entry.provider} · {entry.language} · {sizeMb}MB</span>
                              </div>
                              <span className="text-[9px] font-mono text-zinc-600">{ago}</span>
                              <button
                                onClick={async (e) => {
                                  e.stopPropagation();
                                  if (!confirm(`Delete dub "${entry.profile}"?`)) return;
                                  try {
                                    await deleteTTSAudio(videoMeta.video_id, entry.filename);
                                    setTtsList(prev => prev.filter(e => e.filename !== entry.filename));
                                  } catch { /* ignore */ }
                                }}
                                className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/20 text-zinc-600 hover:text-red-400 transition-all"
                                title="Delete dub"
                              >
                                <span className="material-symbols-outlined text-sm">delete</span>
                              </button>
                              {isPlaying && (
                                <audio
                                  className="tts-player"
                                  autoPlay
                                  src={audioUrl}
                                  onEnded={() => setPlayingTts(null)}
                                  style={{ display: 'none' }}
                                />
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {ttsError && (
                    <div className="bg-error/10 border border-error/30 text-error text-xs p-3 rounded-lg flex items-center gap-2">
                      <span className="material-symbols-outlined text-sm">error</span>
                      {ttsError}
                    </div>
                  )}
                </div>}
              </div>
            )}

        </div>
        )}
      </section>
    </div>
  );
}

export default VideoDetailPage;
