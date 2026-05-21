import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { TTSPreview } from '../components/TTSPreview';
import { SubtitleEditorPanel } from '../components/SubtitleEditorPanel';
import {
  getVideo, getSrt, postTranscribe, postTranslate, postTTS,
  subscribeSSE, getProfiles, getTTSProfiles, getTTSProviders, getTTSVoices,
  getTTSAudioUrl, getTTSList, deleteTTSAudio, getRawVideoUrl,
  patchVideoTitle, postTTSPreview,
} from '../api/client';
import type { TTSAudioEntry } from '../api/client';
import type {
  VideoMetadata, SubtitleSegment, TranslationProfileSummary,
  VoiceProfileConfig, TTSProviderInfo, VoiceInfo,
} from '../api/types';
import { loadApiKeys, loadLLMPrefs, saveLLMPrefs, storageGet, storageSet } from '../utils/storage';

const PLATFORM_INFO: Record<string, { label: string; subLangLabel: string; constraint: string }> = {
  tiktok: { label: 'TikTok', subLangLabel: 'Vietnamese', constraint: '9:16 / 10min / 4GB' },
  youtube: { label: 'YouTube', subLangLabel: 'English', constraint: '9:16 / Shorts / 256GB' },
  facebook: { label: 'Facebook', subLangLabel: 'Vietnamese', constraint: '9:16 / 15min / 4GB' },
  x: { label: 'X / Twitter', subLangLabel: 'English', constraint: '9:16 / 2:20 / 512MB' },
};

function VideoDetailPage() {
  const { videoId } = useParams<{ videoId: string }>();
  const navigate = useNavigate();

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
  const [selectedVoiceId, setSelectedVoiceId] = useState(() => storageGet('tts_voice_id') || '');
  const [voiceIdInput, setVoiceIdInput] = useState(() => storageGet('tts_voice_id') || '');
  const [voiceIdSaved, setVoiceIdSaved] = useState(false);
  const [ttsApiKey, setTtsApiKey] = useState('');
  const [ttsLanguage, setTtsLanguage] = useState('vi');
  const [playbackSpeed, setPlaybackSpeed] = useState(() => {
    const saved = parseFloat(storageGet('tts_playback_speed') || '');
    return Number.isFinite(saved) && saved >= 1.0 && saved <= 2.0 ? saved : 1.5;
  });
  const [underlayDb, setUnderlayDb] = useState(() => {
    const saved = parseFloat(storageGet('tts_underlay_db') || '');
    return Number.isFinite(saved) && saved >= -24 && saved <= 0 ? saved : -12;
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

  const MODEL_OPTIONS: Record<string, { label: string; value: string }[]> = {
    deepseek: [
      { label: 'DeepSeek V3', value: 'deepseek-chat' },
      { label: 'DeepSeek R1', value: 'deepseek-reasoner' },
    ],
    anthropic: [
      { label: 'Claude Sonnet 4', value: 'claude-sonnet-4-20250514' },
      { label: 'Claude Haiku 3.5', value: 'claude-3-5-haiku-20241022' },
      { label: 'Claude Opus 4', value: 'claude-opus-4-20250514' },
    ],
    openai: [
      { label: 'GPT-4o', value: 'gpt-4o' },
      { label: 'GPT-4o Mini', value: 'gpt-4o-mini' },
      { label: 'GPT-4.1', value: 'gpt-4.1' },
      { label: 'GPT-4.1 Mini', value: 'gpt-4.1-mini' },
    ],
  };

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
        setSelectedVoiceId(voices[0].name);
      }
    } catch {
      setTtsVoices([]);
    }
  }, []);

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
    setTtsVoices([]);
    setTtsGenerated(false);
    if (provider === 'elevenlabs') {
      // Load saved voice ID for ElevenLabs — no voice list fetch needed
      const savedId = storageGet('tts_voice_id') || '';
      setSelectedVoiceId(savedId);
      setVoiceIdInput(savedId);
    } else {
      setSelectedVoiceId('');
      setVoiceIdInput('');
      // Auto-fetch voice list for non-ElevenLabs providers
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


  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb="Video Detail" />

      <section className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Back button + title */}

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

        <div className="space-y-6">
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
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${
                    videoMeta.status === 'exported' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    : videoMeta.status === 'translated' ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                    : 'bg-primary/10 text-primary border border-primary/20'
                  }`}>
                    {videoMeta.status === 'exported' ? 'EXPORTED' : videoMeta.status === 'translated' ? 'TRANSLATED' : 'TRANSCRIBED'}
                  </span>
                  <a
                    href={getRawVideoUrl(videoMeta.video_id)}
                    download
                    className="p-1.5 hover:bg-surface-container-highest rounded transition-colors text-zinc-400"
                    title="Download MP4"
                  >
                    <span className="material-symbols-outlined text-sm">save_alt</span>
                  </a>
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

          {/* Not transcribed yet — show extract button */}
          {videoMeta && !videoMeta.has_srt && !isTranscribing && (
            <div className="bg-surface-container-low rounded-xl p-8 border border-outline-variant/10 flex flex-col items-center gap-4 text-center">
              <span className="material-symbols-outlined text-4xl text-zinc-600">subtitles_off</span>
              <p className="text-sm text-zinc-400">No subtitles extracted yet</p>
              <button
                onClick={handleTranscribe}
                className="bg-primary text-on-primary-fixed px-6 py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 active:scale-95 transition-all"
              >
                <span>Extract Subtitles</span>
                <span className="material-symbols-outlined text-sm">document_scanner</span>
              </button>
            </div>
          )}

          {/* Transcription Progress */}
          {isTranscribing && (
            <div className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/10">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-full border-2 border-primary border-t-transparent animate-spin"></div>
                <div className="flex-1">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-xs font-bold uppercase tracking-widest text-primary">Extracting Subtitles (OCR)...</span>
                    <span className="text-[10px] font-mono text-zinc-500">PADDLEOCR</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-on-surface-variant font-mono">Current Stage:</span>
                    <span className="text-[11px] font-medium text-emerald-400">{transcribeMessage}</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Re-Extract button (below editor when already transcribed) */}
          {videoMeta && videoMeta.has_srt && !isTranscribing && (
            <div className="flex items-center gap-3">
              <button
                onClick={handleTranscribe}
                className="bg-surface-container-highest text-on-surface px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 whitespace-nowrap active:scale-95 transition-all hover:bg-surface-container-high"
              >
                <span className="material-symbols-outlined text-sm">document_scanner</span>
                <span>Re-Extract Subtitles (OCR)</span>
              </button>
            </div>
          )}

            {/* Translation Panel */}
            {videoMeta && videoMeta.has_srt && (
              <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
                <button
                  onClick={() => togglePanel('translate')}
                  className="w-full p-4 border-b border-outline-variant/10 flex justify-between items-center hover:bg-surface-container/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-lg">translate</span>
                    <span className="text-xs font-bold uppercase tracking-widest">LLM Translation</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      onClick={(e) => { e.stopPropagation(); navigate('/profiles'); }}
                      className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline flex items-center gap-1"
                    >
                      <span className="material-symbols-outlined text-xs">settings</span>
                      Profiles
                    </span>
                    <span className={`material-symbols-outlined text-sm text-zinc-500 transition-transform ${openPanels.has('translate') ? 'rotate-180' : ''}`}>expand_more</span>
                  </div>
                </button>
                {openPanels.has('translate') && <div className="p-5 space-y-4">
                  {/* Profile Selector */}
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">Translation Profile</label>
                      <div className="flex gap-2 items-center">
                        <select
                          value={selectedProfile}
                          onChange={(e) => setSelectedProfile(e.target.value)}
                          className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                        >
                          {profiles.map((p) => (
                            <option key={p.name} value={p.name}>
                              {p.name} ({p.target_language})
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <button
                      onClick={handleTranslate}
                      disabled={isTranslating || !selectedProfile}
                      className="bg-primary text-on-primary-fixed px-5 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 whitespace-nowrap active:scale-95 transition-all disabled:opacity-50 mt-4"
                    >
                      <span>{isTranslating ? 'Translating...' : 'Translate'}</span>
                      <span className="material-symbols-outlined text-sm">translate</span>
                    </button>
                  </div>

                  {/* Backend & Model */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">Backend</label>
                      <select
                        value={llmBackend}
                        onChange={(e) => {
                          const val = e.target.value;
                          setLlmBackend(val);
                          const models = MODEL_OPTIONS[val];
                          const firstModel = models?.length ? models[0].value : '';
                          if (firstModel) setLlmModel(firstModel);
                          saveLLMPrefs(val, firstModel);
                          if (val === 'deepseek') {
                            setLlmBaseUrl('https://api.deepseek.com');
                          } else {
                            setLlmBaseUrl('');
                          }
                        }}
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                      >
                        <option value="deepseek">DeepSeek</option>
                        <option value="anthropic">Anthropic</option>
                        <option value="openai">OpenAI</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">Model</label>
                      <select
                        value={llmModel}
                        onChange={(e) => { setLlmModel(e.target.value); saveLLMPrefs(llmBackend, e.target.value); }}
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                      >
                        {(MODEL_OPTIONS[llmBackend] || []).map((m) => (
                          <option key={m.value} value={m.value}>
                            {m.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* API Key Warning */}
                  {!llmApiKey && (
                    <div className="bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs p-3 rounded-lg flex items-center gap-2">
                      <span className="material-symbols-outlined text-sm">warning</span>
                      <span>No API key configured for <strong>{llmBackend}</strong>.</span>
                      <button
                        onClick={() => navigate('/settings#apikeys')}
                        className="ml-auto text-[10px] font-bold uppercase tracking-wider text-amber-300 hover:text-amber-200 flex items-center gap-1 whitespace-nowrap"
                      >
                        <span className="material-symbols-outlined text-xs">settings</span>
                        Configure
                      </button>
                    </div>
                  )}

                  {/* Profile Description */}
                  {selectedProfile && profiles.find((p) => p.name === selectedProfile) && (
                    <div className="text-[11px] text-on-surface-variant bg-surface-container-highest/50 rounded p-3">
                      {profiles.find((p) => p.name === selectedProfile)?.description}
                    </div>
                  )}

                  {/* Translation Progress / Result */}
                  {isTranslating && (
                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="text-[10px] font-mono text-zinc-500 uppercase">{translateMessage}</span>
                        <span className="text-xs font-bold font-mono text-primary">{translateProgress.toFixed(0)}%</span>
                      </div>
                      <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden">
                        <div
                          className="bg-primary h-full transition-all duration-500 shadow-[0_0_8px_rgba(208,188,255,0.4)]"
                          style={{ width: `${translateProgress}%` }}
                        />
                      </div>
                    </div>
                  )}
                  {!isTranslating && translateMessage === 'Translation complete' && (
                    <div className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs p-3 rounded-lg flex items-center gap-2">
                      <span className="material-symbols-outlined text-sm">check_circle</span>
                      Translation complete — see translated subtitles in the SRT Preview panel
                      <button onClick={() => setTranslateMessage('')} className="ml-auto text-emerald-500/50 hover:text-emerald-400">
                        <span className="material-symbols-outlined text-sm">close</span>
                      </button>
                    </div>
                  )}
                </div>}
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
                            storageSet('tts_voice_id', voiceIdInput);
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
                        onChange={(e) => { setSelectedVoiceId(e.target.value); setTtsGenerated(false); }}
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
      </section>
    </div>
  );
}

export default VideoDetailPage;
