import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { postDownload, getVideos, getVideo, subscribeSSE, deleteVideo, getProfiles, postPipeline, getTTSProviders, getTTSProfiles } from '../api/client';
import type { VideoMetadata, TranslationProfileSummary, TTSProviderInfo, VoiceProfileConfig } from '../api/types';
import { loadApiKeys, loadLLMPrefs, saveLLMPrefs } from '../utils/storage';

function PipelinePage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState('');
  const [allVideos, setAllVideos] = useState<VideoMetadata[]>([]);
  const [error, setError] = useState('');
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  // Pipeline state
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [downloadMessage, setDownloadMessage] = useState('');
  const [isPipeline, setIsPipeline] = useState(false);
  const [pipelineStage, setPipelineStage] = useState('');
  const [pipelineProgress, setPipelineProgress] = useState(0);
  const [pipelineMessage, setPipelineMessage] = useState('');

  // Pipeline config
  const [profiles, setProfiles] = useState<TranslationProfileSummary[]>([]);
  const [selectedProfile, setSelectedProfile] = useState('');
  const [ttsProviders, setTtsProviders] = useState<TTSProviderInfo[]>([]);
  const [selectedTtsProvider, setSelectedTtsProvider] = useState('edge');
  const [ttsProfiles, setTtsProfiles] = useState<Record<string, VoiceProfileConfig>>({});
  const [selectedTtsProfile, setSelectedTtsProfile] = useState('female-vi-natural');
  const [savedPrefs] = useState(loadLLMPrefs);
  const [llmBackend, setLlmBackend] = useState(savedPrefs.backend);
  const [llmModel, setLlmModel] = useState(savedPrefs.model);
  const [llmApiKey, setLlmApiKey] = useState('');

  const MODEL_OPTIONS: Record<string, { label: string; value: string }[]> = {
    deepseek: [{ label: 'DeepSeek V3', value: 'deepseek-chat' }, { label: 'DeepSeek R1', value: 'deepseek-reasoner' }],
    anthropic: [{ label: 'Claude Sonnet 4', value: 'claude-sonnet-4-20250514' }, { label: 'Claude Haiku 3.5', value: 'claude-3-5-haiku-20241022' }],
    openai: [{ label: 'GPT-4o', value: 'gpt-4o' }, { label: 'GPT-4o Mini', value: 'gpt-4o-mini' }],
  };

  useEffect(() => {
    const keys = loadApiKeys();
    const keyMap: Record<string, string> = { anthropic: keys.anthropic, openai: keys.openai, deepseek: keys.deepseek };
    setLlmApiKey(keyMap[llmBackend] || '');
  }, [llmBackend]);

  const loadVideos = useCallback(async () => {
    try { setAllVideos((await getVideos()).videos); } catch { /* */ }
  }, []);

  useEffect(() => {
    loadVideos();
    getProfiles().then(p => { setProfiles(p); if (p.length > 0) setSelectedProfile(p[0].name); }).catch(() => {});
    getTTSProviders().then(setTtsProviders).catch(() => {});
    getTTSProfiles().then(setTtsProfiles).catch(() => {});
  }, [loadVideos]);

  const handleDownload = async () => {
    if (!url.trim()) return;
    setError(''); setIsDownloading(true); setDownloadProgress(0); setDownloadMessage('Starting download...');
    try {
      const { task_id } = await postDownload(url.trim());
      const es = subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') { setDownloadProgress((data.progress as number) * 100); setDownloadMessage(data.message as string); }
        else if (eventType === 'complete') {
          setIsDownloading(false); setDownloadProgress(100); setDownloadMessage('Download complete');
          const videoId = (data as Record<string, unknown>).video_id as string;
          if (videoId) navigate(`/videos/${videoId}`);
          loadVideos(); es.close();
        } else if (eventType === 'error') { setIsDownloading(false); setError(data.message as string); es.close(); }
      });
    } catch (e) { setIsDownloading(false); setError(e instanceof Error ? e.message : 'Download failed'); }
  };

  const handlePipeline = async () => {
    if (!url.trim()) return;
    setError(''); setIsPipeline(true); setPipelineStage('download'); setPipelineProgress(0); setPipelineMessage('Starting download...');
    try {
      const { task_id } = await postPipeline(url.trim(), selectedProfile || undefined);
      const es = subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') {
          setPipelineStage((data.stage as string) || ''); setPipelineProgress((data.progress as number) * 100); setPipelineMessage(data.message as string);
        } else if (eventType === 'complete') {
          setIsPipeline(false); setPipelineProgress(100); setPipelineMessage('Pipeline complete');
          const videoId = (data as Record<string, unknown>).video_id as string;
          if (videoId) navigate(`/videos/${videoId}`);
          loadVideos(); es.close();
        } else if (eventType === 'error') { setIsPipeline(false); setError(data.message as string); es.close(); }
      });
    } catch (e) { setIsPipeline(false); setError(e instanceof Error ? e.message : 'Pipeline failed'); }
  };

  const handleDeleteVideo = async (videoId: string) => {
    try { await deleteVideo(videoId); setDeleteConfirmId(null); loadVideos(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Failed to delete'); setDeleteConfirmId(null); }
  };

  const formatDuration = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${Math.floor(s % 60).toString().padStart(2, '0')}`;

  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb="Pipeline" />

      <section className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* URL Input + Buttons */}
        <div className="bg-surface-container-low rounded-xl shadow-sm overflow-hidden">
          <div className="flex items-center bg-surface-container-lowest p-2 rounded-t-lg gap-3 focus-within:ring-1 focus-within:ring-primary/40 transition-shadow">
            <div className="pl-3 text-on-surface-variant">
              <span className="material-symbols-outlined">link</span>
            </div>
            <input
              className="flex-1 bg-transparent border-none focus:ring-0 text-on-surface placeholder:text-zinc-600 text-sm py-3"
              placeholder="Paste Douyin share link or URL"
              type="text" value={url} onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handlePipeline()}
            />
            <button onClick={handlePipeline} disabled={isDownloading || isPipeline || !url.trim()}
              className="bg-primary text-on-primary-fixed px-6 py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 hover:brightness-110 active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed">
              <span>{isPipeline ? 'Processing...' : 'Process'}</span>
              <span className="material-symbols-outlined text-sm">play_arrow</span>
            </button>
            <button onClick={handleDownload} disabled={isDownloading || isPipeline || !url.trim()}
              className="bg-surface-container-highest text-on-surface px-4 py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 hover:bg-surface-container-high active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed">
              <span>{isDownloading ? 'Downloading...' : 'Download Only'}</span>
              <span className="material-symbols-outlined text-sm">download</span>
            </button>
          </div>

          {/* Pipeline config */}
          <div className="border-t border-outline-variant/10 px-4 py-3 space-y-3">
            {/* Row 1: Extraction + Translation */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="space-y-1">
                <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">Extraction</label>
                <div className="flex items-center h-8 px-3 bg-surface-container-highest rounded text-[11px] text-on-surface">
                  <span className="material-symbols-outlined text-xs mr-1.5 text-primary">document_scanner</span>
                  OCR (PaddleOCR)
                </div>
              </div>
              <div className="space-y-1">
                <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">Translation Profile</label>
                <select value={selectedProfile} onChange={(e) => setSelectedProfile(e.target.value)}
                  className="w-full bg-surface-container-highest border-none text-[11px] text-on-surface h-8 px-2 rounded focus:ring-0">
                  <option value="">Skip translation</option>
                  {profiles.map((p) => <option key={p.name} value={p.name}>{p.name} ({p.target_language})</option>)}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">LLM Backend</label>
                <select value={llmBackend} onChange={(e) => {
                  const val = e.target.value; setLlmBackend(val);
                  const m = MODEL_OPTIONS[val]; if (m?.length) { setLlmModel(m[0].value); saveLLMPrefs(val, m[0].value); }
                }} className="w-full bg-surface-container-highest border-none text-[11px] text-on-surface h-8 px-2 rounded focus:ring-0">
                  <option value="deepseek">DeepSeek</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">LLM Model</label>
                <select value={llmModel} onChange={(e) => { setLlmModel(e.target.value); saveLLMPrefs(llmBackend, e.target.value); }}
                  className="w-full bg-surface-container-highest border-none text-[11px] text-on-surface h-8 px-2 rounded focus:ring-0">
                  {(MODEL_OPTIONS[llmBackend] || []).map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </div>
            </div>
            {/* Row 2: TTS config */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="space-y-1">
                <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">TTS Provider</label>
                <select value={selectedTtsProvider} onChange={(e) => setSelectedTtsProvider(e.target.value)}
                  className="w-full bg-surface-container-highest border-none text-[11px] text-on-surface h-8 px-2 rounded focus:ring-0">
                  {ttsProviders.map((p) => <option key={p.id} value={p.id}>{p.name}{p.free ? ' (Free)' : ''}</option>)}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">TTS Voice Profile</label>
                <select value={selectedTtsProfile} onChange={(e) => setSelectedTtsProfile(e.target.value)}
                  className="w-full bg-surface-container-highest border-none text-[11px] text-on-surface h-8 px-2 rounded focus:ring-0">
                  {Object.entries(ttsProfiles).map(([name, p]) => (
                    <option key={name} value={name}>{name} ({p.language})</option>
                  ))}
                </select>
              </div>
              <div className="lg:col-span-2 flex items-end">
                <div className="flex items-center gap-3 text-[10px] text-on-surface-variant">
                  <span className="material-symbols-outlined text-xs text-primary">info</span>
                  Pipeline runs: Download → OCR → Translate → open in <strong className="text-primary ml-0.5">Video Studio</strong> for TTS & Export
                </div>
              </div>
            </div>
            {/* API key warning */}
            {selectedProfile && !llmApiKey && (
              <div className="flex items-center gap-1.5 text-amber-400">
                <span className="material-symbols-outlined text-xs">warning</span>
                <span className="text-[10px]">No <strong>{llmBackend}</strong> API key — </span>
                <button onClick={() => navigate('/settings#apikeys')} className="text-[10px] font-bold underline">Configure in Settings</button>
              </div>
            )}
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="bg-error/10 border border-error/30 text-error text-xs p-3 rounded-lg flex items-center gap-2">
            <span className="material-symbols-outlined text-sm">error</span>
            {error}
            <button onClick={() => setError('')} className="ml-auto"><span className="material-symbols-outlined text-sm">close</span></button>
          </div>
        )}

        {/* Download Progress */}
        {isDownloading && (
          <div className="bg-surface-container-low rounded-xl overflow-hidden">
            <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-lg">downloading</span>
                <span className="text-xs font-bold uppercase tracking-widest">Active Download</span>
              </div>
              <span className="text-lg font-black font-mono text-primary tracking-tighter">{downloadProgress.toFixed(0)}%</span>
            </div>
            <div className="p-5 space-y-3">
              <div className="text-sm font-semibold truncate">{url}</div>
              <div className="text-[10px] text-zinc-500 font-mono uppercase">{downloadMessage}</div>
              <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden">
                <div className="bg-primary h-full transition-all duration-500 shadow-[0_0_8px_rgba(208,188,255,0.4)]" style={{ width: `${downloadProgress}%` }} />
              </div>
            </div>
          </div>
        )}

        {/* Pipeline Progress */}
        {isPipeline && (
          <div className="bg-surface-container-low rounded-xl overflow-hidden border border-primary/20">
            <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-lg">rocket_launch</span>
                <span className="text-xs font-bold uppercase tracking-widest">Pipeline</span>
              </div>
              <span className="text-lg font-black font-mono text-primary tracking-tighter">{pipelineProgress.toFixed(0)}%</span>
            </div>
            <div className="p-5 space-y-4">
              <div className="flex items-center gap-2">
                {[
                  { key: 'download', label: 'Download', icon: 'download' },
                  { key: 'transcribe', label: 'Extract Subtitles', icon: 'document_scanner' },
                  ...(selectedProfile ? [{ key: 'translate', label: 'Translate', icon: 'translate' }] : []),
                ].map((s, i) => {
                  const isDone = (s.key === 'download' && pipelineStage !== 'download') ||
                    (s.key === 'transcribe' && (pipelineStage === 'translate' || pipelineProgress >= 100)) ||
                    (s.key === 'translate' && pipelineProgress >= 100);
                  const isActive = pipelineStage === s.key;
                  return (
                    <div key={s.key} className="flex items-center gap-2">
                      {i > 0 && <div className={`w-8 h-px ${isDone || isActive ? 'bg-primary' : 'bg-zinc-700'}`} />}
                      <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                        isDone ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          : isActive ? 'bg-primary/10 text-primary border border-primary/30'
                            : 'bg-surface-container-highest text-zinc-600 border border-outline-variant/10'
                      }`}>
                        <span className="material-symbols-outlined text-xs">{isDone ? 'check_circle' : isActive ? 'pending' : s.icon}</span>
                        {s.label}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="flex items-center gap-3">
                <div className="w-6 h-6 rounded-full border-2 border-primary border-t-transparent animate-spin shrink-0" />
                <span className="text-[11px] font-medium text-emerald-400">{pipelineMessage}</span>
              </div>
              <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden">
                <div className="bg-primary h-full transition-all duration-500 shadow-[0_0_8px_rgba(208,188,255,0.4)]" style={{ width: `${pipelineProgress}%` }} />
              </div>
            </div>
          </div>
        )}

        {/* Video Library */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold uppercase tracking-[0.2em] text-zinc-500">Video Library</h2>
            <span className="text-[10px] font-mono text-zinc-600">{allVideos.length} videos</span>
          </div>
          {allVideos.length === 0 && !isDownloading && !isPipeline && (
            <div className="bg-surface-container-low rounded-xl p-12 flex flex-col items-center justify-center text-center">
              <span className="material-symbols-outlined text-5xl text-zinc-700 mb-4">video_library</span>
              <h3 className="text-sm font-bold text-on-surface-variant mb-1">No Videos Yet</h3>
              <p className="text-xs text-zinc-500">Paste a Douyin URL above to download your first video</p>
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {allVideos.map((v) => {
              const isConfirmingDelete = deleteConfirmId === v.video_id;
              return (
                <div key={v.video_id}
                  className="relative bg-surface-container-lowest p-3 rounded-lg flex items-center gap-4 hover:bg-surface-container-low transition-colors group border border-outline-variant/5 cursor-pointer"
                  onClick={() => navigate(`/videos/${v.video_id}`)}>
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
                    <div className="text-[11px] font-bold truncate">{v.title || `${v.video_id}.mp4`}</div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[9px] font-mono text-zinc-500">{v.size}</span>
                      <span className="w-1 h-1 rounded-full bg-zinc-700" />
                      <span className="text-[9px] font-mono text-zinc-500">{formatDuration(v.duration)}</span>
                      <span className="w-1 h-1 rounded-full bg-zinc-700" />
                      <span className={`text-[9px] font-bold uppercase ${v.has_srt ? 'text-emerald-500' : 'text-primary'}`}>
                        {v.has_srt ? 'Transcribed' : 'Downloaded'}
                      </span>
                      {v.srt_languages.length > 0 && (
                        <span className="font-mono text-[8px] text-zinc-500">{v.srt_languages.join(', ').toUpperCase()}</span>
                      )}
                    </div>
                  </div>
                  <span className="material-symbols-outlined text-xs text-zinc-600 group-hover:text-primary">arrow_forward</span>
                  {/* Delete */}
                  {isConfirmingDelete ? (
                    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <button onClick={() => handleDeleteVideo(v.video_id)}
                        className="text-[9px] font-bold text-error bg-error/10 border border-error/30 px-2 py-1 rounded hover:bg-error/20">Confirm</button>
                      <button onClick={() => setDeleteConfirmId(null)}
                        className="text-[9px] font-bold text-zinc-400 px-2 py-1 rounded hover:text-on-surface">Cancel</button>
                    </div>
                  ) : (
                    <button onClick={(e) => { e.stopPropagation(); setDeleteConfirmId(v.video_id); }}
                      className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-error/10 rounded text-zinc-500 hover:text-error" title="Delete video">
                      <span className="material-symbols-outlined text-sm">delete</span>
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </div>
  );
}

export default PipelinePage;
