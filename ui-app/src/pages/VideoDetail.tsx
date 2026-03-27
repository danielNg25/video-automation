import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { TTSPreview } from '../components/TTSPreview';
import {
  getVideo, getSrt, postTranscribe, postTranslate, postTTS,
  subscribeSSE, getProfiles, getTTSProfiles, getTTSProviders, getTTSVoices,
  getTTSAudioUrl, getTTSList, getPlatforms, getRawVideoUrl,
  getSrtDownloadUrl, patchVideoTitle, postTTSPreview,
  postExport, postExportPreview, getExportedVideoUrl,
} from '../api/client';
import type { TTSAudioEntry } from '../api/client';
import type {
  VideoMetadata, SubtitleSegment, TranslationProfileSummary,
  VoiceProfileConfig, TTSProviderInfo, VoiceInfo, PlatformSpec,
} from '../api/types';
import { loadApiKeys, loadLLMPrefs, saveLLMPrefs } from '../utils/storage';

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
  const [selectedTtsProvider, setSelectedTtsProvider] = useState('edge');
  const [ttsProfiles, setTtsProfiles] = useState<Record<string, VoiceProfileConfig>>({});
  const [selectedTtsProfile, setSelectedTtsProfile] = useState('female-vi-natural');
  const [ttsVoices, setTtsVoices] = useState<VoiceInfo[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState('');
  const [ttsApiKey, setTtsApiKey] = useState('');
  const [ttsLanguage, setTtsLanguage] = useState('vi');
  const [useDirectVoice, setUseDirectVoice] = useState(false);
  const [isGeneratingTts, setIsGeneratingTts] = useState(false);
  const [ttsProgress, setTtsProgress] = useState({ pct: 0, message: '' });
  const [ttsGenerated, setTtsGenerated] = useState(false);
  const [ttsError, setTtsError] = useState('');
  const [ttsList, setTtsList] = useState<TTSAudioEntry[]>([]);
  const [playingTts, setPlayingTts] = useState<string | null>(null);

  // Export state
  const [platformSpecs, setPlatformSpecs] = useState<Record<string, PlatformSpec>>({});
  const [exportSubLang, setExportSubLang] = useState<string | null>(null);
  const [exportTtsFile, setExportTtsFile] = useState<string | null>(null);
  const [exportVideoVol, setExportVideoVol] = useState(100);
  const [exportTtsVol, setExportTtsVol] = useState(100);
  const [isExporting, setIsExporting] = useState(false);
  const [exportProgress, setExportProgress] = useState({ pct: 0, message: '' });
  const [exportError, setExportError] = useState('');
  const [exportDone, setExportDone] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);

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

  const loadSrt = useCallback(async (vid: string, lang: string) => {
    try {
      const srt = await getSrt(vid, lang);
      setSrtSegments(srt.segments);
      setPreviewLanguage(lang);
    } catch {
      setSrtSegments([]);
    }
  }, []);

  const loadVoicesForProvider = useCallback(async (provider: string, apiKey?: string) => {
    try {
      const voices = await getTTSVoices(undefined, provider, apiKey);
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
          setExportSubLang(video.srt_languages[0]);
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

      try {
        const specs = await getPlatforms();
        setPlatformSpecs(specs);
      } catch { /* platforms not available */ }

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
        useDirectVoice ? selectedTtsProvider : undefined,
        useDirectVoice ? selectedVoiceId : undefined,
        ttsApiKey || undefined,
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
    setUseDirectVoice(true);
    setTtsVoices([]);
    setSelectedVoiceId('');
    setTtsGenerated(false);
    const info = ttsProviders.find(p => p.id === provider);
    if (info && !info.requires_key) {
      loadVoicesForProvider(provider);
    }
  };

  void platformSpecs; // loaded for potential future use

  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb="Video Detail" />

      <section className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Back button + title */}
        <div className="flex items-center gap-3 mb-6">
          <button onClick={() => navigate('/download')} className="flex items-center gap-1 text-xs text-on-surface-variant hover:text-on-surface">
            <span className="material-symbols-outlined text-sm">arrow_back</span>
            Back to Pipeline
          </button>
          <h1 className="text-lg font-semibold text-on-surface truncate">{videoMeta?.title || videoId}</h1>
        </div>

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

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column */}
          <div className="lg:col-span-8 space-y-6">

            {/* Video Card */}
            {videoMeta && (
              <div className="bg-surface-container-low rounded-xl overflow-hidden flex flex-col md:flex-row border border-primary/20">
                <div className="w-full md:w-64 aspect-video bg-surface-container-highest relative group overflow-hidden">
                  {videoMeta.thumbnail ? (
                    <img src={videoMeta.thumbnail} alt={videoMeta.title} className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <span className="material-symbols-outlined text-4xl text-zinc-600">movie</span>
                    </div>
                  )}
                  <div className="absolute bottom-2 right-2 bg-black/80 text-white text-[10px] px-1.5 py-0.5 rounded font-mono">
                    {formatDuration(videoMeta.duration)}
                  </div>
                </div>
                <div className="flex-1 p-5 flex flex-col justify-between">
                  <div>
                    <div className="flex justify-between items-start mb-2">
                      {editingTitle ? (
                        <input
                          autoFocus
                          className="text-sm font-bold bg-surface-container-highest border border-primary/30 rounded px-2 py-1 text-on-surface focus:ring-1 focus:ring-primary flex-1 mr-2"
                          value={titleDraft}
                          onChange={(e) => setTitleDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSaveTitle();
                            if (e.key === 'Escape') setEditingTitle(false);
                          }}
                          onBlur={handleSaveTitle}
                        />
                      ) : (
                        <h3
                          className="text-sm font-bold leading-tight cursor-pointer group/title flex items-center gap-1.5"
                          onClick={() => {
                            setEditingTitle(true);
                            setTitleDraft(videoMeta.title || videoMeta.video_id);
                          }}
                        >
                          {videoMeta.title || videoMeta.video_id}
                          <span className="material-symbols-outlined text-xs text-zinc-600 opacity-0 group-hover/title:opacity-100 transition-opacity">
                            edit
                          </span>
                        </h3>
                      )}
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${
                          videoMeta.has_srt
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-primary/10 text-primary border border-primary/20'
                        }`}
                      >
                        {videoMeta.has_srt ? 'TRANSCRIBED' : 'DOWNLOADED'}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-y-2 gap-x-4">
                      <div className="flex flex-col">
                        <span className="text-[10px] text-zinc-500 uppercase tracking-tighter">Author</span>
                        <span className="text-xs font-medium">@{videoMeta.author || 'unknown'}</span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[10px] text-zinc-500 uppercase tracking-tighter">Resolution</span>
                        <span className="text-xs font-medium font-mono">{videoMeta.resolution || 'N/A'}</span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[10px] text-zinc-500 uppercase tracking-tighter">Size</span>
                        <span className="text-xs font-medium font-mono">{videoMeta.size}</span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[10px] text-zinc-500 uppercase tracking-tighter">Codec</span>
                        <span className="text-xs font-medium font-mono">{videoMeta.codec || 'N/A'}</span>
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 space-y-3">
                    <div className="flex items-center gap-3">
                      <span className="text-[10px] text-zinc-500 font-mono uppercase whitespace-nowrap">
                        OCR — Auto-detect (CN)
                      </span>
                      <button
                        onClick={handleTranscribe}
                        disabled={isTranscribing}
                        className="bg-primary text-on-primary-fixed px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 whitespace-nowrap active:scale-95 transition-all disabled:opacity-50"
                      >
                        <span>{isTranscribing ? 'Extracting...' : videoMeta.has_srt ? 'Re-Extract' : 'Extract Subtitles'}</span>
                        <span className="material-symbols-outlined text-sm">document_scanner</span>
                      </button>
                      {videoMeta.has_srt && (
                        <button
                          onClick={() => navigate(`/editor/${videoMeta.video_id}?lang=${previewLanguage || videoMeta.srt_languages[0] || 'zh'}`)}
                          className="bg-surface-container-highest text-on-surface px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 whitespace-nowrap active:scale-95 transition-all hover:bg-surface-container-high"
                        >
                          <span>Edit Subtitles</span>
                          <span className="material-symbols-outlined text-sm">edit_note</span>
                        </button>
                      )}
                      <a
                        href={getRawVideoUrl(videoMeta.video_id)}
                        download
                        className="bg-surface-container-highest text-on-surface px-3 py-2 rounded-md font-bold text-xs flex items-center gap-1.5 whitespace-nowrap active:scale-95 transition-all hover:bg-surface-container-high"
                        title="Download MP4"
                      >
                        <span className="material-symbols-outlined text-sm">save_alt</span>
                      </a>
                    </div>
                  </div>
                </div>
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

            {/* Translation Panel */}
            {videoMeta && videoMeta.has_srt && (
              <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
                <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-lg">translate</span>
                    <span className="text-xs font-bold uppercase tracking-widest">LLM Translation</span>
                  </div>
                  <button
                    onClick={() => navigate('/profiles')}
                    className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline flex items-center gap-1"
                  >
                    <span className="material-symbols-outlined text-xs">settings</span>
                    Manage Profiles
                  </button>
                </div>
                <div className="p-5 space-y-4">
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
                </div>
              </div>
            )}

            {/* TTS Dubbing Panel */}
            {videoMeta && videoMeta.has_srt && videoMeta.srt_languages.some(l => l !== 'zh') && (
              <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
                <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-lg">record_voice_over</span>
                    <span className="text-xs font-bold uppercase tracking-widest">TTS Dubbing</span>
                  </div>
                  <span className="font-mono text-[10px] text-primary bg-primary/10 px-2 py-0.5 rounded uppercase">
                    {selectedTtsProvider}
                  </span>
                </div>
                <div className="p-5 space-y-4">
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
                        onChange={(e) => { setTtsLanguage(e.target.value); setTtsGenerated(false); }}
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

                  {/* API Key for paid providers */}
                  {ttsProviders.find(p => p.id === selectedTtsProvider)?.requires_key && (
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">API Key</label>
                      <div className="flex gap-2">
                        <input
                          type="password"
                          value={ttsApiKey}
                          onChange={(e) => setTtsApiKey(e.target.value)}
                          placeholder={`Enter ${selectedTtsProvider} API key`}
                          className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary placeholder:text-zinc-600"
                        />
                        <button
                          onClick={() => loadVoicesForProvider(selectedTtsProvider, ttsApiKey)}
                          disabled={!ttsApiKey}
                          className="bg-primary/20 text-primary px-3 py-2 rounded text-[10px] font-bold uppercase hover:bg-primary/30 disabled:opacity-50"
                        >
                          Load Voices
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Voice selection: Profiles / All Voices tabs */}
                  <div>
                    <div className="flex items-center gap-3 mb-2">
                      <button
                        onClick={() => setUseDirectVoice(false)}
                        className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded ${!useDirectVoice ? 'bg-primary/20 text-primary' : 'text-zinc-500 hover:text-on-surface'}`}
                      >
                        Profiles
                      </button>
                      <button
                        onClick={() => { setUseDirectVoice(true); if (ttsVoices.length === 0 && !ttsProviders.find(p => p.id === selectedTtsProvider)?.requires_key) loadVoicesForProvider(selectedTtsProvider); }}
                        className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded ${useDirectVoice ? 'bg-primary/20 text-primary' : 'text-zinc-500 hover:text-on-surface'}`}
                      >
                        All Voices
                      </button>
                    </div>

                    {!useDirectVoice ? (
                      <select
                        value={selectedTtsProfile}
                        onChange={(e) => handleTtsProfileChange(e.target.value)}
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                      >
                        {Object.entries(ttsProfiles).map(([name, profile]) => (
                          <option key={name} value={name}>
                            {name} ({profile.provider} / {profile.language})
                          </option>
                        ))}
                      </select>
                    ) : (
                      <select
                        value={selectedVoiceId}
                        onChange={(e) => { setSelectedVoiceId(e.target.value); setTtsGenerated(false); }}
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                      >
                        {ttsVoices.length === 0 && <option value="">No voices loaded</option>}
                        {ttsVoices.map((v) => (
                          <option key={v.name} value={v.name}>
                            {v.friendly_name || v.name} ({v.gender}) — {v.language}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>

                  {/* Voice Preview */}
                  {(() => {
                    const previewVoice = useDirectVoice
                      ? selectedVoiceId
                      : ttsProfiles[selectedTtsProfile]?.voice;
                    const previewProvider = useDirectVoice
                      ? selectedTtsProvider
                      : ttsProfiles[selectedTtsProfile]?.provider || 'edge';
                    return previewVoice ? (
                      <div className="flex items-center gap-3">
                        <TTSPreview
                          voice={previewVoice}
                          provider={previewProvider}
                          speed={useDirectVoice ? '+0%' : ttsProfiles[selectedTtsProfile]?.speed}
                          pitch={useDirectVoice ? '+0Hz' : ttsProfiles[selectedTtsProfile]?.pitch}
                          apiKey={ttsApiKey || undefined}
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
                </div>
              </div>
            )}

            {/* Export Panel */}
            {videoMeta && (
              <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
                <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-lg">movie_edit</span>
                    <span className="text-xs font-bold uppercase tracking-widest">Export Video</span>
                  </div>
                </div>
                <div className="p-5 space-y-4">
                  {/* Subtitle Language */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Subtitles</label>
                    <div className="flex gap-2">
                      <button onClick={() => setExportSubLang(null)}
                        className={`px-3 py-1.5 rounded text-[10px] font-bold uppercase ${exportSubLang === null ? 'bg-primary/20 text-primary' : 'bg-surface-container-highest text-zinc-400 hover:text-on-surface'}`}>
                        None
                      </button>
                      {(videoMeta.srt_languages || []).map(lang => (
                        <button key={lang} onClick={() => setExportSubLang(lang)}
                          className={`px-3 py-1.5 rounded text-[10px] font-bold uppercase ${exportSubLang === lang ? 'bg-primary/20 text-primary' : 'bg-surface-container-highest text-zinc-400 hover:text-on-surface'}`}>
                          {lang === 'zh' ? 'Chinese' : lang === 'vi' ? 'Vietnamese' : lang === 'en' ? 'English' : lang}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Dub Audio Selection */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Dub Audio</label>
                    <select value={exportTtsFile || ''} onChange={e => setExportTtsFile(e.target.value || null)}
                      className="w-full bg-surface-container border-none text-xs text-on-surface h-9 px-3 rounded-lg focus:ring-1 focus:ring-primary">
                      <option value="">No dub</option>
                      {ttsList.map(entry => (
                        <option key={entry.filename} value={entry.filename}>
                          {entry.profile} ({entry.provider} · {entry.language})
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Volume Sliders */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <div className="flex justify-between">
                        <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Video Volume</label>
                        <span className="text-[10px] font-mono text-primary">{exportVideoVol}%</span>
                      </div>
                      <input type="range" min={0} max={200} value={exportVideoVol}
                        onChange={e => setExportVideoVol(Number(e.target.value))}
                        className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer" />
                    </div>
                    <div className="space-y-1.5">
                      <div className="flex justify-between">
                        <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Dub Volume</label>
                        <span className="text-[10px] font-mono text-primary">{exportTtsVol}%</span>
                      </div>
                      <input type="range" min={0} max={200} value={exportTtsVol}
                        onChange={e => setExportTtsVol(Number(e.target.value))}
                        className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                        disabled={!exportTtsFile} />
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex gap-3">
                    <button
                      disabled={isPreviewing}
                      onClick={async () => {
                        if (!videoMeta) return;
                        setIsPreviewing(true); setExportError('');
                        try {
                          const blob = await postExportPreview(
                            videoMeta.video_id, exportSubLang, exportTtsFile,
                            exportVideoVol / 100, exportTtsVol / 100,
                          );
                          if (previewUrl) URL.revokeObjectURL(previewUrl);
                          setPreviewUrl(URL.createObjectURL(blob));
                        } catch (e) {
                          setExportError(e instanceof Error ? e.message : 'Preview failed');
                        } finally {
                          setIsPreviewing(false);
                        }
                      }}
                      className="flex-1 py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 bg-surface-container-highest text-on-surface hover:bg-surface-container-high transition-colors disabled:opacity-50">
                      <span className="material-symbols-outlined text-sm">{isPreviewing ? 'progress_activity' : 'preview'}</span>
                      {isPreviewing ? 'Rendering...' : 'Preview 5s'}
                    </button>
                    <button
                      disabled={isExporting}
                      onClick={async () => {
                        if (!videoMeta) return;
                        setIsExporting(true); setExportError(''); setExportDone(false);
                        setExportProgress({ pct: 0, message: 'Starting...' });
                        try {
                          const { task_id } = await postExport(
                            videoMeta.video_id, exportSubLang, exportTtsFile,
                            exportVideoVol / 100, exportTtsVol / 100,
                          );
                          const es = subscribeSSE(task_id, (eventType, data) => {
                            if (eventType === 'progress') {
                              setExportProgress({
                                pct: Math.round((data.progress as number) * 100),
                                message: data.message as string,
                              });
                            } else if (eventType === 'complete') {
                              setIsExporting(false); setExportDone(true);
                              setExportProgress({ pct: 100, message: 'Export complete' });
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
                      }}
                      className="flex-1 py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 bg-gradient-to-r from-primary to-primary-container text-on-primary-fixed hover:shadow-[0_0_20px_rgba(160,120,255,0.3)] transition-all disabled:opacity-50">
                      <span className="material-symbols-outlined text-sm">{isExporting ? 'progress_activity' : 'movie_edit'}</span>
                      {isExporting ? 'Exporting...' : 'Export Full Video'}
                    </button>
                  </div>

                  {/* Export Progress */}
                  {isExporting && (
                    <div className="space-y-1">
                      <div className="flex justify-between text-[10px] font-mono">
                        <span className="text-on-surface-variant">{exportProgress.message}</span>
                        <span className="text-primary">{exportProgress.pct}%</span>
                      </div>
                      <div className="h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                        <div className="h-full bg-primary transition-all duration-300" style={{ width: `${exportProgress.pct}%` }} />
                      </div>
                    </div>
                  )}

                  {exportError && (
                    <div className="p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">{exportError}</div>
                  )}

                  {/* Preview Player */}
                  {previewUrl && (
                    <div className="space-y-1">
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Preview</label>
                      <video controls autoPlay className="w-full max-h-[300px] rounded-lg bg-black" src={previewUrl} />
                    </div>
                  )}

                  {/* Export Output Player */}
                  {exportDone && videoMeta && (
                    <div className="space-y-1">
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Exported Video</label>
                      <video controls className="w-full max-h-[300px] rounded-lg bg-black"
                        src={getExportedVideoUrl(videoMeta.video_id)} />
                      <a href={getExportedVideoUrl(videoMeta.video_id)} download
                        className="inline-flex items-center gap-1 text-[10px] text-primary hover:underline font-bold mt-1">
                        <span className="material-symbols-outlined text-xs">download</span>
                        Download
                      </a>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Right Column: SRT Preview */}
          <div className="lg:col-span-4 flex flex-col max-h-[600px]">
            <div className="bg-surface-container-low rounded-xl flex-1 flex flex-col border border-outline-variant/10 overflow-hidden">
              <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center bg-surface-container-high/30">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-zinc-400">subtitles</span>
                  <span className="text-xs font-bold uppercase tracking-widest">SRT Preview</span>
                  {srtSegments.length > 0 && (
                    <span className="text-[10px] font-mono text-zinc-500">({srtSegments.length} segments)</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {videoMeta && videoMeta.srt_languages.length > 1 && (
                    <select
                      value={previewLanguage}
                      onChange={(e) => {
                        if (videoMeta) loadSrt(videoMeta.video_id, e.target.value);
                      }}
                      className="bg-surface-container-highest border-none text-[10px] text-on-surface py-1 px-2 rounded focus:ring-0 font-mono uppercase"
                    >
                      {videoMeta.srt_languages.map((lang) => (
                        <option key={lang} value={lang}>
                          {lang}
                        </option>
                      ))}
                    </select>
                  )}
                  {videoMeta && videoMeta.srt_languages.length === 1 && (
                    <span className="text-[10px] font-mono text-zinc-500 uppercase">{previewLanguage}</span>
                  )}
                  {videoMeta && previewLanguage && (
                    <a
                      href={getSrtDownloadUrl(videoMeta.video_id, previewLanguage)}
                      download
                      className="p-1.5 hover:bg-surface-container-highest rounded transition-colors text-zinc-400"
                      title="Export SRT"
                    >
                      <span className="material-symbols-outlined text-sm">download</span>
                    </a>
                  )}
                  <button className="p-1.5 hover:bg-surface-container-highest rounded transition-colors text-zinc-400" title="Copy Text">
                    <span className="material-symbols-outlined text-sm">content_copy</span>
                  </button>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-2 space-y-1">
                {srtSegments.length > 0 ? (
                  srtSegments.map((seg) => (
                    <div
                      key={seg.id}
                      className="group p-3 rounded hover:bg-surface-container-high transition-colors cursor-pointer border-l-2 border-transparent hover:border-primary"
                    >
                      <div className="flex justify-between mb-1">
                        <span className="text-[10px] font-mono text-primary font-bold">
                          {seg.startTime} → {seg.endTime}
                        </span>
                        <span className="text-[10px] text-zinc-600 font-mono">#{seg.id}</span>
                      </div>
                      <p className="text-xs leading-relaxed text-on-surface-variant group-hover:text-on-surface">
                        {seg.text}
                      </p>
                    </div>
                  ))
                ) : (
                  <div className="flex flex-col items-center justify-center h-full text-center p-8">
                    <span className="material-symbols-outlined text-3xl text-zinc-700 mb-3">subtitles_off</span>
                    <p className="text-xs text-zinc-500">
                      {isTranscribing
                        ? 'Transcription in progress...'
                        : 'Extract subtitles to see them here'}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

export default VideoDetailPage;
