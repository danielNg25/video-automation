import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { postDownload, postTranscribe, getVideos, getVideo, getSrt, subscribeSSE, patchVideoTitle, deleteVideo, getProfiles, getProfile, postTranslate, createProfile, updateProfile, deleteProfileApi, getRawVideoUrl, getSrtDownloadUrl, getPlatform } from '../api/client';
import type { VideoMetadata, SubtitleSegment, TranslationProfileSummary, TranslationProfile } from '../api/types';

function DownloadTranscribePage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState('');
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [downloadMessage, setDownloadMessage] = useState('');
  const [videoMeta, setVideoMeta] = useState<VideoMetadata | null>(null);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcribeMessage, setTranscribeMessage] = useState('');
  const [srtSegments, setSrtSegments] = useState<SubtitleSegment[]>([]);
  const [allVideos, setAllVideos] = useState<VideoMetadata[]>([]);
  const [selectedLanguage, setSelectedLanguage] = useState('zh');
  const [previewLanguage, setPreviewLanguage] = useState('');
  const [error, setError] = useState('');
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  // Translation state
  const [profiles, setProfiles] = useState<TranslationProfileSummary[]>([]);
  const [selectedProfile, setSelectedProfile] = useState('');
  const [isTranslating, setIsTranslating] = useState(false);
  const [translateMessage, setTranslateMessage] = useState('');
  const [translateProgress, setTranslateProgress] = useState(0);
  const [showProfileEditor, setShowProfileEditor] = useState(false);
  const [editingProfile, setEditingProfile] = useState<TranslationProfile | null>(null);
  const [profileDraft, setProfileDraft] = useState<TranslationProfile>({
    name: '', description: '', target_language: 'vi', source_language: 'zh',
    style_guide: '', example_pairs: [],
  });
  const [llmBackend, setLlmBackend] = useState('anthropic');
  const [llmModel, setLlmModel] = useState('claude-sonnet-4-20250514');
  const [llmApiKey, setLlmApiKey] = useState('');
  const [llmBaseUrl, setLlmBaseUrl] = useState('');
  const [serverPlatform, setServerPlatform] = useState('darwin');

  useEffect(() => {
    getPlatform().then((r) => setServerPlatform(r.platform)).catch(() => {});
  }, []);

  const LOCAL_MODELS_MACOS = [
    { label: 'Qwen 2.5 14B (4-bit)', value: 'mlx-community/Qwen2.5-14B-Instruct-4bit' },
    { label: 'Qwen 2.5 7B (4-bit)', value: 'mlx-community/Qwen2.5-7B-Instruct-4bit' },
    { label: 'Qwen 2.5 32B (4-bit)', value: 'mlx-community/Qwen2.5-32B-Instruct-4bit' },
    { label: 'Llama 3.1 8B (4-bit)', value: 'mlx-community/Meta-Llama-3.1-8B-Instruct-4bit' },
    { label: 'Mistral 7B (4-bit)', value: 'mlx-community/Mistral-7B-Instruct-v0.3-4bit' },
  ];

  const LOCAL_MODELS_LINUX = [
    { label: 'Qwen 2.5 14B (Q4)', value: 'Qwen/Qwen2.5-14B-Instruct-GGUF' },
    { label: 'Qwen 2.5 7B (Q4)', value: 'Qwen/Qwen2.5-7B-Instruct-GGUF' },
    { label: 'Qwen 2.5 32B (Q4)', value: 'Qwen/Qwen2.5-32B-Instruct-GGUF' },
    { label: 'Llama 3.1 8B (Q4)', value: 'meta-llama/Llama-3.1-8B-Instruct-GGUF' },
    { label: 'Mistral 7B (Q4)', value: 'mistralai/Mistral-7B-Instruct-v0.3-GGUF' },
  ];

  const MODEL_OPTIONS: Record<string, { label: string; value: string }[]> = {
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
    local: serverPlatform === 'darwin' ? LOCAL_MODELS_MACOS : LOCAL_MODELS_LINUX,
  };

  const loadProfiles = useCallback(async () => {
    try {
      const p = await getProfiles();
      setProfiles(p);
      if (p.length > 0 && !selectedProfile) {
        setSelectedProfile(p[0].name);
      }
    } catch {
      // API not available yet
    }
  }, [selectedProfile]);

  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  const loadVideos = useCallback(async () => {
    try {
      const resp = await getVideos();
      setAllVideos(resp.videos);
    } catch {
      // API not available yet
    }
  }, []);

  useEffect(() => {
    loadVideos();
  }, [loadVideos]);

  const loadSrt = useCallback(async (videoId: string, lang: string) => {
    try {
      const srt = await getSrt(videoId, lang);
      setSrtSegments(srt.segments);
      setPreviewLanguage(lang);
    } catch {
      setSrtSegments([]);
    }
  }, []);

  const selectVideo = useCallback(
    async (video: VideoMetadata) => {
      setVideoMeta(video);
      setSrtSegments([]);
      setPreviewLanguage('');
      setError('');
      // Load first available SRT
      if (video.srt_languages.length > 0) {
        await loadSrt(video.video_id, video.srt_languages[0]);
      }
    },
    [loadSrt],
  );

  const handleDownload = async () => {
    if (!url.trim()) return;
    setError('');
    setIsDownloading(true);
    setDownloadProgress(0);
    setDownloadMessage('Starting download...');
    setVideoMeta(null);
    setSrtSegments([]);

    try {
      const { task_id } = await postDownload(url.trim());
      const es = subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') {
          setDownloadProgress((data.progress as number) * 100);
          setDownloadMessage(data.message as string);
        } else if (eventType === 'complete') {
          setIsDownloading(false);
          setDownloadProgress(100);
          setDownloadMessage('Download complete');
          setVideoMeta(data as unknown as VideoMetadata);
          loadVideos();
          es.close();
        } else if (eventType === 'error') {
          setIsDownloading(false);
          setError(data.message as string);
          es.close();
        }
      });
    } catch (e) {
      setIsDownloading(false);
      setError(e instanceof Error ? e.message : 'Download failed');
    }
  };

  const handleTranscribe = async () => {
    if (!videoMeta) return;
    setError('');
    setIsTranscribing(true);
    setTranscribeMessage('Loading transcription model...');
    setSrtSegments([]);

    const task = selectedLanguage === 'en' ? 'translate' : 'transcribe';
    const lang = selectedLanguage === 'en' ? 'zh' : selectedLanguage;

    try {
      const { task_id } = await postTranscribe(videoMeta.video_id, lang, task);
      const es = subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') {
          setTranscribeMessage(data.message as string);
        } else if (eventType === 'complete') {
          setIsTranscribing(false);
          setTranscribeMessage('Transcription complete');
          const srtLang = (data.language as string) || 'zh';
          loadSrt(videoMeta.video_id, srtLang);
          // Refresh video list and update current video meta
          loadVideos().then(async () => {
            const updated = await getVideo(videoMeta.video_id);
            setVideoMeta(updated);
          });
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

  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  const handleSaveTitle = async () => {
    if (!videoMeta || !titleDraft.trim()) return;
    try {
      const updated = await patchVideoTitle(videoMeta.video_id, titleDraft.trim());
      setVideoMeta(updated);
      setEditingTitle(false);
      loadVideos();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update title');
    }
  };

  const handleDeleteVideo = async (videoId: string) => {
    try {
      await deleteVideo(videoId);
      if (videoMeta?.video_id === videoId) {
        setVideoMeta(null);
        setSrtSegments([]);
      }
      setDeleteConfirmId(null);
      loadVideos();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete video');
      setDeleteConfirmId(null);
    }
  };

  const handleTranslate = async () => {
    if (!videoMeta || !selectedProfile) return;
    setError('');
    setIsTranslating(true);
    setTranslateProgress(0);
    setTranslateMessage('Loading translation profile...');

    // Determine source language: prefer zh, fall back to first available
    const sourceLang = videoMeta.srt_languages.includes('zh')
      ? 'zh'
      : videoMeta.srt_languages.includes('en')
        ? 'en'
        : videoMeta.srt_languages[0] || 'zh';

    try {
      const overrides: { backend?: string; model?: string; api_key?: string; base_url?: string } = {};
      overrides.backend = llmBackend;
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
          if (targetLang) loadSrt(videoMeta.video_id, targetLang);
          // Refresh video metadata to get updated srt_languages
          loadVideos().then(async () => {
            const updated = await getVideo(videoMeta.video_id);
            setVideoMeta(updated);
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

  const handleSaveProfile = async () => {
    try {
      if (editingProfile) {
        await updateProfile(editingProfile.name, profileDraft);
      } else {
        await createProfile(profileDraft);
      }
      setShowProfileEditor(false);
      setEditingProfile(null);
      loadProfiles();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save profile');
    }
  };

  const handleEditProfile = async (name: string) => {
    try {
      const full = await getProfile(name);
      setEditingProfile(full);
      setProfileDraft(full);
      setShowProfileEditor(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load profile');
    }
  };

  const handleDeleteProfile = async (name: string) => {
    try {
      await deleteProfileApi(name);
      loadProfiles();
      if (selectedProfile === name) setSelectedProfile('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete profile');
    }
  };

  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb="Transcribe" />

      <section className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* URL Input Section */}
        <div className="bg-surface-container-low p-1 rounded-xl shadow-sm">
          <div className="flex items-center bg-surface-container-lowest p-2 rounded-lg gap-3 focus-within:ring-1 focus-within:ring-primary/40 transition-shadow">
            <div className="pl-3 text-on-surface-variant">
              <span className="material-symbols-outlined">link</span>
            </div>
            <input
              className="flex-1 bg-transparent border-none focus:ring-0 text-on-surface placeholder:text-zinc-600 text-sm py-3"
              placeholder="Paste Douyin share link or URL"
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleDownload()}
            />
            <button
              onClick={handleDownload}
              disabled={isDownloading || !url.trim()}
              className="bg-primary text-on-primary-fixed px-6 py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 hover:brightness-110 active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span>{isDownloading ? 'Downloading...' : 'Download'}</span>
              <span className="material-symbols-outlined text-sm">download</span>
            </button>
          </div>
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
          <div className="lg:col-span-7 space-y-6">
            {/* Active Download Card */}
            {isDownloading && (
              <div className="bg-surface-container-low rounded-xl overflow-hidden">
                <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-lg">downloading</span>
                    <span className="text-xs font-bold uppercase tracking-widest">Active Download</span>
                  </div>
                  <span className="text-[10px] font-mono text-zinc-500">ENGINE: DOUYIN API + YT-DLP</span>
                </div>
                <div className="p-5 space-y-4">
                  <div className="flex justify-between items-end mb-1">
                    <div className="space-y-1">
                      <div className="text-sm font-semibold truncate max-w-[300px]">{url}</div>
                      <div className="text-[10px] text-zinc-500 font-mono uppercase">{downloadMessage}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-lg font-black font-mono text-primary tracking-tighter">
                        {downloadProgress.toFixed(1)}%
                      </div>
                    </div>
                  </div>
                  <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden">
                    <div
                      className="bg-primary h-full transition-all duration-500 shadow-[0_0_8px_rgba(208,188,255,0.4)]"
                      style={{ width: `${downloadProgress}%` }}
                    ></div>
                  </div>
                </div>
              </div>
            )}

            {/* Video Result Card — shown when a video is selected or just downloaded */}
            {videoMeta && !isDownloading && (
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
                  <div className="mt-6 flex items-center gap-3">
                    <div className="flex-1 flex gap-px rounded-md overflow-hidden border border-outline-variant/20">
                      <select
                        value={selectedLanguage}
                        onChange={(e) => setSelectedLanguage(e.target.value)}
                        className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 focus:ring-0"
                      >
                        <option value="zh">Chinese (Mandarin)</option>
                        <option value="vi">Vietnamese</option>
                        <option value="en">English (Translate)</option>
                      </select>
                    </div>
                    <button
                      onClick={handleTranscribe}
                      disabled={isTranscribing}
                      className="bg-primary text-on-primary-fixed px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 whitespace-nowrap active:scale-95 transition-all disabled:opacity-50"
                    >
                      <span>{isTranscribing ? 'Transcribing...' : videoMeta.has_srt ? 'Re-Transcribe' : 'Transcribe'}</span>
                      <span className="material-symbols-outlined text-sm">neurology</span>
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
            )}

            {/* Transcription Progress */}
            {isTranscribing && (
              <div className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/10">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-full border-2 border-primary border-t-transparent animate-spin"></div>
                  <div className="flex-1">
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-xs font-bold uppercase tracking-widest text-primary">Transcribing Audio...</span>
                      <span className="text-[10px] font-mono text-zinc-500">WHISPER v3 LARGE</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-on-surface-variant font-mono">Current Stage:</span>
                      <span className="text-[11px] font-medium text-emerald-400">{transcribeMessage}</span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Translation Panel — shown after transcription */}
            {videoMeta && videoMeta.has_srt && !isDownloading && (
              <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
                <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-primary text-lg">translate</span>
                    <span className="text-xs font-bold uppercase tracking-widest">LLM Translation</span>
                  </div>
                  <button
                    onClick={() => {
                      setEditingProfile(null);
                      setProfileDraft({
                        name: '', description: '', target_language: 'vi', source_language: 'zh',
                        style_guide: '', example_pairs: [],
                      });
                      setShowProfileEditor(!showProfileEditor);
                    }}
                    className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline"
                  >
                    {showProfileEditor ? 'Cancel' : '+ New Profile'}
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
                        {selectedProfile && (
                          <>
                            <button
                              onClick={() => handleEditProfile(selectedProfile)}
                              className="p-1.5 hover:bg-surface-container-highest rounded transition-colors text-zinc-400"
                              title="Edit profile"
                            >
                              <span className="material-symbols-outlined text-sm">edit</span>
                            </button>
                            <button
                              onClick={() => handleDeleteProfile(selectedProfile)}
                              className="p-1.5 hover:bg-error/10 rounded transition-colors text-zinc-400 hover:text-error"
                              title="Delete profile"
                            >
                              <span className="material-symbols-outlined text-sm">delete</span>
                            </button>
                          </>
                        )}
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

                  {/* Model & API Key */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">Backend</label>
                      <select
                        value={llmBackend}
                        onChange={(e) => {
                          const val = e.target.value;
                          setLlmBackend(val);
                          const models = MODEL_OPTIONS[val];
                          if (models?.length) setLlmModel(models[0].value);
                          setLlmBaseUrl('');
                          if (val === 'local') setLlmApiKey('');
                        }}
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                      >
                        <option value="anthropic">Anthropic</option>
                        <option value="openai">OpenAI</option>
                        <option value="local">Local (Ollama / vLLM)</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">Model</label>
                      <select
                        value={llmModel}
                        onChange={(e) => setLlmModel(e.target.value)}
                        className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                      >
                        {(MODEL_OPTIONS[llmBackend] || []).map((m) => (
                          <option key={m.value} value={m.value}>
                            {m.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    {llmBackend !== 'local' && (
                      <div>
                        <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block mb-1">API Key</label>
                        <input
                          type="password"
                          value={llmApiKey}
                          onChange={(e) => setLlmApiKey(e.target.value)}
                          className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary"
                          placeholder="Uses env var if empty"
                        />
                      </div>
                    )}
                    {llmBackend === 'local' && (
                      <div className="flex items-end">
                        <span className="text-[10px] text-zinc-500 py-2">
                          {serverPlatform === 'darwin'
                            ? 'Runs in-process via mlx-lm (Apple Silicon)'
                            : 'Runs in-process via llama-cpp-python (CPU/CUDA)'}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Profile Description */}
                  {selectedProfile && profiles.find((p) => p.name === selectedProfile) && (
                    <div className="text-[11px] text-on-surface-variant bg-surface-container-highest/50 rounded p-3">
                      {profiles.find((p) => p.name === selectedProfile)?.description}
                    </div>
                  )}

                  {/* Translation Progress */}
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

                  {/* Profile Editor */}
                  {showProfileEditor && (
                    <div className="border border-outline-variant/20 rounded-lg p-4 space-y-3 bg-surface-container-lowest">
                      <h4 className="text-xs font-bold uppercase tracking-widest">
                        {editingProfile ? 'Edit Profile' : 'New Profile'}
                      </h4>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="text-[10px] text-zinc-500 uppercase block mb-1">Name</label>
                          <input
                            className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary"
                            value={profileDraft.name}
                            onChange={(e) => setProfileDraft({ ...profileDraft, name: e.target.value })}
                            placeholder="my-profile-vi"
                          />
                        </div>
                        <div>
                          <label className="text-[10px] text-zinc-500 uppercase block mb-1">Target Language</label>
                          <select
                            className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                            value={profileDraft.target_language}
                            onChange={(e) => setProfileDraft({ ...profileDraft, target_language: e.target.value })}
                          >
                            <option value="vi">Vietnamese</option>
                            <option value="en">English</option>
                            <option value="ko">Korean</option>
                            <option value="ja">Japanese</option>
                            <option value="es">Spanish</option>
                          </select>
                        </div>
                      </div>
                      <div>
                        <label className="text-[10px] text-zinc-500 uppercase block mb-1">Description</label>
                        <input
                          className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary"
                          value={profileDraft.description}
                          onChange={(e) => setProfileDraft({ ...profileDraft, description: e.target.value })}
                          placeholder="Short description of this translation style"
                        />
                      </div>
                      <div>
                        <label className="text-[10px] text-zinc-500 uppercase block mb-1">Source Language</label>
                        <select
                          className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
                          value={profileDraft.source_language}
                          onChange={(e) => setProfileDraft({ ...profileDraft, source_language: e.target.value })}
                        >
                          <option value="zh">Chinese</option>
                          <option value="en">English</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-[10px] text-zinc-500 uppercase block mb-1">Style Guide</label>
                        <textarea
                          className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary h-32 resize-y"
                          value={profileDraft.style_guide}
                          onChange={(e) => setProfileDraft({ ...profileDraft, style_guide: e.target.value })}
                          placeholder="Describe the personality, tone, and rules for translation..."
                        />
                      </div>
                      <div>
                        <div className="flex justify-between items-center mb-2">
                          <label className="text-[10px] text-zinc-500 uppercase">Example Pairs</label>
                          <button
                            onClick={() =>
                              setProfileDraft({
                                ...profileDraft,
                                example_pairs: [...profileDraft.example_pairs, { source: '', target: '' }],
                              })
                            }
                            className="text-[10px] text-primary font-bold uppercase hover:underline"
                          >
                            + Add
                          </button>
                        </div>
                        {profileDraft.example_pairs.map((pair, i) => (
                          <div key={i} className="flex gap-2 mb-2 items-center">
                            <input
                              className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-1 focus:ring-primary"
                              placeholder="Source text"
                              value={pair.source}
                              onChange={(e) => {
                                const pairs = [...profileDraft.example_pairs];
                                pairs[i] = { ...pairs[i], source: e.target.value };
                                setProfileDraft({ ...profileDraft, example_pairs: pairs });
                              }}
                            />
                            <span className="text-zinc-600 text-[10px]">→</span>
                            <input
                              className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-1 focus:ring-primary"
                              placeholder="Target text"
                              value={pair.target}
                              onChange={(e) => {
                                const pairs = [...profileDraft.example_pairs];
                                pairs[i] = { ...pairs[i], target: e.target.value };
                                setProfileDraft({ ...profileDraft, example_pairs: pairs });
                              }}
                            />
                            <button
                              onClick={() => {
                                const pairs = profileDraft.example_pairs.filter((_, j) => j !== i);
                                setProfileDraft({ ...profileDraft, example_pairs: pairs });
                              }}
                              className="text-zinc-500 hover:text-error"
                            >
                              <span className="material-symbols-outlined text-sm">close</span>
                            </button>
                          </div>
                        ))}
                      </div>
                      <div className="flex justify-end gap-2 pt-2">
                        <button
                          onClick={() => { setShowProfileEditor(false); setEditingProfile(null); }}
                          className="px-4 py-2 text-xs font-bold uppercase tracking-wider text-zinc-400 hover:text-on-surface"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={handleSaveProfile}
                          disabled={!profileDraft.name.trim()}
                          className="bg-primary text-on-primary-fixed px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider disabled:opacity-50"
                        >
                          {editingProfile ? 'Update' : 'Save'} Profile
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Empty state when nothing is happening */}
            {!isDownloading && !videoMeta && !isTranscribing && (
              <div className="bg-surface-container-low rounded-xl p-12 flex flex-col items-center justify-center text-center">
                <span className="material-symbols-outlined text-5xl text-zinc-700 mb-4">video_library</span>
                <h3 className="text-sm font-bold text-on-surface-variant mb-1">No Video Selected</h3>
                <p className="text-xs text-zinc-500">Paste a Douyin URL above to download, or click a video below to transcribe it</p>
              </div>
            )}
          </div>

          {/* Right Column: SRT Preview */}
          <div className="lg:col-span-5 flex flex-col max-h-[600px]">
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
                        : 'Download and transcribe a video to see subtitles here'}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Video Library — clickable to select for transcription */}
        {allVideos.length > 0 && (
          <div className="space-y-4 pt-6">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-bold uppercase tracking-[0.2em] text-zinc-500">Video Library</h2>
              <span className="text-[10px] font-mono text-zinc-600">{allVideos.length} videos</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {allVideos.map((v) => {
                const isSelected = videoMeta?.video_id === v.video_id;
                const isConfirmingDelete = deleteConfirmId === v.video_id;
                return (
                  <div
                    key={v.video_id}
                    className={`relative bg-surface-container-lowest p-3 rounded-lg flex items-center gap-4 hover:bg-surface-container-low transition-colors group border cursor-pointer ${
                      isSelected ? 'border-primary/50 bg-primary/5' : 'border-outline-variant/5'
                    }`}
                    onClick={() => selectVideo(v)}
                  >
                    <div className="w-16 h-10 bg-surface-container-high rounded overflow-hidden flex-shrink-0">
                      {v.thumbnail ? (
                        <img src={v.thumbnail} alt={v.title} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full bg-surface-container-highest flex items-center justify-center">
                          <span className="material-symbols-outlined text-sm text-zinc-600">movie</span>
                        </div>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[11px] font-bold truncate">
                        {v.title || `${v.video_id}.mp4`}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[9px] font-mono text-zinc-500">{v.size}</span>
                        <span className="w-1 h-1 rounded-full bg-zinc-700"></span>
                        <span
                          className={`text-[9px] font-bold uppercase ${
                            v.has_srt ? 'text-emerald-500' : 'text-primary'
                          }`}
                        >
                          {v.has_srt ? 'Transcribed' : 'Downloaded'}
                        </span>
                      </div>
                    </div>
                    {isSelected && (
                      <span className="material-symbols-outlined text-primary text-sm">check_circle</span>
                    )}
                    {/* Delete button */}
                    {isConfirmingDelete ? (
                      <div
                        className="flex items-center gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          onClick={() => handleDeleteVideo(v.video_id)}
                          className="text-[9px] font-bold text-error bg-error/10 border border-error/30 px-2 py-1 rounded hover:bg-error/20"
                        >
                          Confirm
                        </button>
                        <button
                          onClick={() => setDeleteConfirmId(null)}
                          className="text-[9px] font-bold text-zinc-400 px-2 py-1 rounded hover:text-on-surface"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteConfirmId(v.video_id);
                        }}
                        className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-error/10 rounded text-zinc-500 hover:text-error"
                        title="Delete video"
                      >
                        <span className="material-symbols-outlined text-sm">delete</span>
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

export default DownloadTranscribePage;
