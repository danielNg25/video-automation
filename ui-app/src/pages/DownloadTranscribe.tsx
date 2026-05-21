import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { postDownload, getVideos, subscribeSSE, deleteVideo, getProfiles, postPipeline, getTTSProviders, getTTSProfiles, getTTSVoices } from '../api/client';
import type { VideoMetadata, TranslationProfileSummary, TTSProviderInfo, VoiceProfileConfig, VoiceInfo } from '../api/types';
import { loadApiKeys, loadLLMPrefs, saveLLMPrefs, storageGet, storageSet } from '../utils/storage';

const PIPELINE_TASK_KEY = 'pipeline_active_task';
const POLL_INTERVAL = 2000; // 2 seconds

function PipelinePage() {
  const navigate = useNavigate();
  const [urlInput, setUrlInput] = useState('');
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

  // Batch state
  const [batchConcurrency, setBatchConcurrency] = useState(3);
  const [batchResults, setBatchResults] = useState<{ completed: number; total: number } | null>(null);

  // Pipeline config
  const [profiles, setProfiles] = useState<TranslationProfileSummary[]>([]);
  const [selectedProfile, setSelectedProfile] = useState('');
  const [ttsProviders, setTtsProviders] = useState<TTSProviderInfo[]>([]);
  const [selectedTtsProvider, setSelectedTtsProvider] = useState(() =>
    storageGet('tts_selected_provider') || 'google'
  );
  const [ttsProfiles, setTtsProfiles] = useState<Record<string, VoiceProfileConfig>>({});
  const [selectedTtsProfile, setSelectedTtsProfile] = useState('female-vi-natural');
  const [ttsVoices, setTtsVoices] = useState<VoiceInfo[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState(() => {
    const provider = storageGet('tts_selected_provider') || 'google';
    return storageGet(`tts_voice_id_${provider}`) || '';
  });
  const [voiceIdInput, setVoiceIdInput] = useState(() => storageGet('tts_voice_id_elevenlabs') || '');
  const [voiceIdSaved, setVoiceIdSaved] = useState(false);
  const [ttsApiKey, setTtsApiKey] = useState('');
  const [playbackSpeed, setPlaybackSpeed] = useState(() => {
    const saved = parseFloat(storageGet('tts_playback_speed') || '');
    return Number.isFinite(saved) && saved >= 1.0 && saved <= 2.0 ? saved : 1.5;
  });
  const [underlayDb, setUnderlayDb] = useState(() => {
    const saved = parseFloat(storageGet('tts_underlay_db') || '');
    return Number.isFinite(saved) && saved >= -24 && saved <= 0 ? saved : -18;
  });
  const [blurEnabled, setBlurEnabled] = useState(true);
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

  // Load voice list when the TTS provider changes.
  useEffect(() => {
    if (selectedTtsProvider === 'elevenlabs') {
      setTtsVoices([]);
      const saved = storageGet('tts_voice_id_elevenlabs') || '';
      setSelectedVoiceId(saved);
      setVoiceIdInput(saved);
      setTtsApiKey('');
      return;
    }
    const keys = loadApiKeys();
    const key = (keys as Record<string, string>)[selectedTtsProvider] || '';
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
        const isValid = !!saved && voices.some(v => v.name === saved);
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

  // Parse URLs from input
  const parsedUrls = urlInput.split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('#'));
  const isBatchMode = parsedUrls.length > 1;
  const url = parsedUrls[0] || '';

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearActiveTask = () => sessionStorage.removeItem(PIPELINE_TASK_KEY);
  const saveActiveTask = (taskId: string, mode: 'single' | 'batch') => {
    sessionStorage.setItem(PIPELINE_TASK_KEY, JSON.stringify({ taskId, mode }));
  };

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const loadVideos = useCallback(async () => {
    try { setAllVideos((await getVideos()).videos); } catch { /* */ }
  }, []);

  // Poll pipeline status endpoint
  const startPolling = useCallback((taskId: string, mode: 'single' | 'batch') => {
    stopPolling();

    const poll = async () => {
      try {
        const r = await fetch(`/api/pipeline/${taskId}`);
        if (!r.ok) { stopPolling(); clearActiveTask(); return; }
        const d = await r.json();

        if (mode === 'batch' && d.children) {
          // Batch: aggregate children progress
          const children = d.children as { video_id: string; status: string; current_stage: string; progress: number; message: string; error: string | null }[];
          const done = children.filter(c => c.status === 'done' || c.status === 'failed').length;
          const total = children.length;
          const failed = children.filter(c => c.status === 'failed');
          // Show the most advanced running child's stage, fall back to batch-level current_stage
          const running = children.find(c => c.status !== 'done' && c.status !== 'failed' && c.current_stage);
          const stage = running?.current_stage || (d.current_stage as string) || '';
          if (stage) {
            setPipelineStage(stage);
          }
          setBatchResults({ completed: done, total });

          // Use average of all children's progress for smooth % updates
          const avgProgress = children.length > 0
            ? children.reduce((sum, c) => sum + (c.progress || 0), 0) / children.length
            : 0;
          setPipelineProgress(avgProgress * 100);

          // Show all running children's messages, one per line
          const runningChildren = children.filter(c => c.message && c.status !== 'done' && c.status !== 'failed');
          const lines = runningChildren.map((c, i) => `#${i + 1} ${c.message}`);
          setPipelineMessage(`[${done}/${total} done]\n${lines.join('\n') || 'Processing...'}`);

          // Check if batch is done
          if (d.status === 'completed' || d.status === 'failed') {
            stopPolling(); setIsPipeline(false); setPipelineProgress(100);
            if (failed.length > 0) {
              const errMsgs = failed.map(c => `${c.video_id}: ${c.error || 'Unknown error'}`).join('\n');
              setError(`${failed.length} of ${total} videos failed:\n${errMsgs}`);
              setPipelineMessage(`Batch done: ${total - failed.length} succeeded, ${failed.length} failed`);
            } else {
              setPipelineMessage('Batch complete');
            }
            setBatchResults(null); setUrlInput(''); loadVideos(); clearActiveTask();
          }
        } else {
          // Single: read stage/progress from state
          setPipelineStage(d.current_stage || '');
          setPipelineProgress((d.progress ?? 0) * 100);
          setPipelineMessage(d.message || '');

          if (d.status === 'completed') {
            stopPolling(); setIsPipeline(false); setPipelineProgress(100); setPipelineMessage('Pipeline complete');
            if (d.video_id) navigate(`/videos/${d.video_id}`);
            loadVideos(); clearActiveTask();
          } else if (d.status === 'failed') {
            stopPolling(); setIsPipeline(false);
            setError(d.error || 'Pipeline failed'); clearActiveTask();
          }
        }
      } catch { /* network error, keep polling */ }
    };

    // Poll immediately then every POLL_INTERVAL
    poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL);
  }, [stopPolling, loadVideos, navigate]);

  useEffect(() => {
    loadVideos();
    getProfiles().then(p => { setProfiles(p); if (p.length > 0) setSelectedProfile(p[0].name); }).catch(() => {});
    getTTSProviders().then(setTtsProviders).catch(() => {});
    getTTSProfiles().then(setTtsProfiles).catch(() => {});

    // Reconnect to active pipeline task if one exists
    const saved = sessionStorage.getItem(PIPELINE_TASK_KEY);
    if (saved) {
      try {
        const { taskId, mode } = JSON.parse(saved) as { taskId: string; mode: 'single' | 'batch' };
        fetch(`/api/pipeline/${taskId}`).then(r => {
          if (!r.ok) { clearActiveTask(); return; }
          return r.json();
        }).then(task => {
          if (!task) return;
          if (task.status === 'running') {
            setIsPipeline(true);
            setPipelineStage(task.current_stage || '');
            setPipelineProgress((task.progress ?? 0) * 100);
            setPipelineMessage(task.message || 'Resuming...');
            startPolling(taskId, mode);
          } else if (task.status === 'completed') {
            clearActiveTask();
          } else if (task.status === 'failed') {
            clearActiveTask();
            if (task.error) setError(task.error);
          } else {
            clearActiveTask();
          }
        }).catch(() => clearActiveTask());
      } catch { clearActiveTask(); }
    }

    return () => { stopPolling(); };
  }, [loadVideos, startPolling, stopPolling]);

  const handleDownload = async () => {
    if (!url) return;
    setError(''); setIsDownloading(true); setDownloadProgress(0); setDownloadMessage('Starting download...');
    try {
      const { task_id } = await postDownload(url);
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
    if (parsedUrls.length === 0) return;

    // Build TTS/LLM overrides from the same Settings store the per-video
    // page reads from, so the pipeline produces output identical to the
    // editor's "Generate TTS" button.
    const apiKeys = loadApiKeys();
    const ttsProfileCfg = ttsProfiles[selectedTtsProfile];
    const ttsProviderName = ttsProfileCfg?.provider || selectedTtsProvider;
    const ttsApiKey =
      ttsProviderName === 'elevenlabs' ? apiKeys.elevenlabs :
      ttsProviderName === 'openai' ? apiKeys.openai :
      ttsProviderName === 'google' ? apiKeys.google : '';
    // All providers now forward a voice override — use the per-provider key,
    // falling back to the in-memory selection if localStorage is empty.
    const ttsVoiceId = storageGet(`tts_voice_id_${ttsProviderName}`) || selectedVoiceId || '';
    const ttsOverrides = {
      tts_provider: ttsProviderName || undefined,
      tts_voice: ttsVoiceId || undefined,
      tts_api_key: ttsApiKey || undefined,
      llm_api_key: llmApiKey || undefined,
      llm_backend: llmBackend || undefined,
      playback_speed: playbackSpeed,
      underlay_db: underlayDb,
    };

    // Batch mode
    if (isBatchMode) {
      setError(''); setIsPipeline(true); setPipelineStage('download'); setPipelineProgress(0);
      setPipelineMessage(`Starting batch: ${parsedUrls.length} videos...`);
      setBatchResults({ completed: 0, total: parsedUrls.length });
      try {
        const res = await fetch('/api/pipeline/batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            urls: parsedUrls,
            platforms: ['youtube', 'tiktok'],
            concurrency: batchConcurrency,
            translate_profile: selectedProfile || null,
            translation_override: selectedProfile ? { backend: llmBackend, model: llmModel, api_key: llmApiKey || undefined } : null,
            tts_profile: selectedTtsProfile || null,
            blur_enabled: blurEnabled,
            ...ttsOverrides,
          }),
        });
        const data = await res.json();
        if (data.batch_id) {
          saveActiveTask(data.batch_id, 'batch');
          startPolling(data.batch_id, 'batch');
        }
      } catch (e) { setIsPipeline(false); setBatchResults(null); setError(e instanceof Error ? e.message : 'Batch failed'); }
      return;
    }

    // Single URL mode
    setError(''); setIsPipeline(true); setPipelineStage('download'); setPipelineProgress(0); setPipelineMessage('Starting download...');
    try {
      const translationOverride = selectedProfile ? { backend: llmBackend, model: llmModel, api_key: llmApiKey || undefined } : undefined;
      const { task_id } = await postPipeline(url, selectedProfile || undefined, 'zh', translationOverride, selectedTtsProfile || undefined, blurEnabled, ttsOverrides);
      saveActiveTask(task_id, 'single');
      startPolling(task_id, 'single');
    } catch (e) { setIsPipeline(false); setError(e instanceof Error ? e.message : 'Pipeline failed'); }
  };

  const handleDeleteVideo = async (videoId: string) => {
    try { await deleteVideo(videoId); setDeleteConfirmId(null); loadVideos(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Failed to delete'); setDeleteConfirmId(null); }
  };

  const formatDuration = (s: number) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${Math.floor(s % 60).toString().padStart(2, '0')}`;

  // Stepper state
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const toggleStep = (n: number) => setExpandedStep(prev => prev === n ? null : n);

  // Step state derivation during pipeline execution
  // All backend stages in order. Steps map to: download→download, transcribe→transcribe,
  // translate→translate, tts→tts, process/upload are post-TTS (all steps done).
  const allStages = ['download', 'transcribe', 'translate', 'tts', 'process', 'upload'];
  const stepStages: Record<string, string[]> = {
    download: ['download'],
    transcribe: ['transcribe'],
    translate: ['translate'],
    tts: ['tts'],
    process: ['process', 'upload'],
  };

  const getStepState = (key: string): 'config' | 'running' | 'done' | 'pending' => {
    if (isDownloading && key === 'download') return 'running';
    if (!isPipeline) return 'config';
    if (pipelineProgress >= 100) return 'done';

    const currentIdx = allStages.indexOf(pipelineStage);
    if (currentIdx === -1) return 'pending';

    // The last stage this step "owns"
    const ownedStages = stepStages[key] || [key];
    const lastOwnedIdx = Math.max(...ownedStages.map(s => allStages.indexOf(s)));
    const firstOwnedIdx = Math.min(...ownedStages.map(s => allStages.indexOf(s)));

    if (currentIdx > lastOwnedIdx) return 'done';
    if (currentIdx >= firstOwnedIdx && currentIdx <= lastOwnedIdx) {
      // For Process step: 'upload' means process is done
      if (key === 'process' && pipelineStage === 'upload') return 'done';
      return 'running';
    }
    return 'pending';
  };

  const steps = [
    { num: 1, key: 'download', icon: 'download', title: 'Download', summary: 'Douyin API + yt-dlp fallback' },
    { num: 2, key: 'transcribe', icon: 'document_scanner', title: 'Extract Subtitles', summary: 'PaddleOCR — auto-detect Chinese subtitles' },
    { num: 3, key: 'translate', icon: 'translate', title: 'Translate', summary: selectedProfile
        ? `Profile: ${selectedProfile} · ${llmBackend === 'deepseek' ? 'DeepSeek' : llmBackend === 'anthropic' ? 'Anthropic' : 'OpenAI'} / ${(MODEL_OPTIONS[llmBackend] || []).find(m => m.value === llmModel)?.label || llmModel}`
        : 'Skipped — no translation profile selected' },
    { num: 4, key: 'tts', icon: 'record_voice_over', title: 'TTS Dubbing', summary: (() => {
        const prov = ttsProviders.find(p => p.id === selectedTtsProvider);
        const prof = ttsProfiles[selectedTtsProfile];
        return `${prov?.name || selectedTtsProvider} · ${selectedTtsProfile}${prof ? ` (${prof.language === 'vi' ? 'Vietnamese' : prof.language === 'en' ? 'English' : prof.language})` : ''}`;
      })() },
    { num: 5, key: 'process', icon: 'movie_edit', title: 'Process & Burn', summary: blurEnabled ? 'Blur original subs · burn translated subs · reformat per platform' : 'Burn translated subs · reformat per platform (blur off)' },
  ];

  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb="Pipeline" />

      <section className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* URL Input — supports single or multiple URLs */}
        <div className="bg-surface-container-low rounded-xl shadow-sm overflow-hidden">
          <div className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-lg">link</span>
                <span className="text-xs font-bold uppercase tracking-widest text-zinc-500">
                  {isBatchMode ? `${parsedUrls.length} URLs` : 'Source URL'}
                </span>
              </div>
              {isBatchMode && (
                <div className="flex items-center gap-3">
                  <span className="text-[10px] font-mono text-zinc-500 uppercase">Concurrency</span>
                  <div className="flex items-center gap-2">
                    <input
                      type="range" min={1} max={5} value={batchConcurrency}
                      onChange={(e) => setBatchConcurrency(Number(e.target.value))}
                      className="w-20 accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                    />
                    <span className="text-xs font-mono text-primary w-4 text-center">{batchConcurrency}</span>
                  </div>
                </div>
              )}
            </div>

            <textarea
              className="w-full bg-surface-container-lowest border-none rounded-lg px-4 py-3 text-sm text-on-surface placeholder:text-zinc-600 focus:ring-1 focus:ring-primary/40 resize-none font-mono"
              placeholder={"Paste Douyin URLs — one per line for batch processing\nhttps://v.douyin.com/xxx\nhttps://v.douyin.com/yyy"}
              rows={isBatchMode ? 4 : 2}
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !isBatchMode) {
                  e.preventDefault();
                  handlePipeline();
                }
              }}
            />

            {/* Batch progress */}
            {batchResults && (
              <div className="space-y-1.5">
                <div className="flex justify-between text-[10px] font-mono">
                  <span className="text-primary">Processing {batchResults.completed}/{batchResults.total} videos...</span>
                  <span className="text-zinc-500">{Math.round((batchResults.completed / batchResults.total) * 100)}%</span>
                </div>
                <div className="w-full h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                  <div className="h-full bg-primary transition-all duration-300"
                    style={{ width: `${(batchResults.completed / batchResults.total) * 100}%` }} />
                </div>
              </div>
            )}

            <div className="flex gap-2">
              <button onClick={handlePipeline} disabled={isDownloading || isPipeline || parsedUrls.length === 0}
                className="bg-primary text-on-primary-fixed px-8 py-3 rounded-lg font-bold text-xs uppercase tracking-wider flex items-center gap-2 hover:brightness-110 active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed">
                <span className="material-symbols-outlined text-sm">{isBatchMode ? 'playlist_play' : 'rocket_launch'}</span>
                <span>{isPipeline ? 'Running...' : isBatchMode ? `Process ${parsedUrls.length} Videos` : 'Run Pipeline'}</span>
              </button>
              {!isBatchMode && (
                <button onClick={handleDownload} disabled={isDownloading || isPipeline || !url}
                  className="bg-surface-container-highest text-on-surface px-5 py-3 rounded-lg font-bold text-xs uppercase tracking-wider flex items-center gap-2 hover:bg-surface-container-high active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed">
                  <span className="material-symbols-outlined text-sm">download</span>
                  <span>{isDownloading ? 'Downloading...' : 'Download Only'}</span>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="bg-error/10 border border-error/30 text-error text-xs p-3 rounded-lg flex items-start gap-2 whitespace-pre-line">
            <span className="material-symbols-outlined text-sm mt-0.5">error</span>
            <span className="flex-1">{error}</span>
            <button onClick={() => setError('')} className="shrink-0"><span className="material-symbols-outlined text-sm">close</span></button>
          </div>
        )}

        {/* Pipeline Stepper */}
        <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
          <div className="p-5 border-b border-outline-variant/10 flex justify-between items-center">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-lg">account_tree</span>
              <span className="text-sm font-bold tracking-tight text-on-surface">Pipeline Steps</span>
            </div>
            {isPipeline && (
              <span className="text-lg font-black font-mono text-primary tracking-tighter">{pipelineProgress.toFixed(0)}%</span>
            )}
          </div>

          <div className="p-5">
            {steps.map((step, i) => {
              const state = getStepState(step.key);
              const isExpanded = expandedStep === step.num;
              const isRunning = state === 'running';
              const isDone = state === 'done';
              const isSkipped = step.key === 'translate' && !selectedProfile;
              const isLast = i === steps.length - 1;

              return (
                <div key={step.key} className="relative">
                  {/* Connector line */}
                  {!isLast && (
                    <div className={`absolute left-[19px] top-[40px] w-0.5 ${isDone ? 'bg-emerald-500/40' : isRunning ? 'bg-primary/40' : 'bg-zinc-700/30'}`}
                      style={{ height: isExpanded ? 'calc(100% - 20px)' : '24px' }} />
                  )}

                  {/* Step header */}
                  <div
                    className={`flex items-center gap-4 p-3 rounded-lg cursor-pointer transition-colors ${
                      isRunning ? 'bg-primary/5' : isExpanded ? 'bg-surface-container-highest/30' : 'hover:bg-surface-container-highest/20'
                    }`}
                    onClick={() => !isPipeline && toggleStep(step.num)}
                  >
                    {/* Step circle */}
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
                      isDone ? 'bg-emerald-500/20 text-emerald-400'
                        : isRunning ? 'bg-primary/20 text-primary'
                          : isSkipped ? 'bg-zinc-800 text-zinc-600'
                            : 'bg-surface-container-highest text-on-surface-variant'
                    }`}>
                      {isDone ? (
                        <span className="material-symbols-outlined text-lg">check</span>
                      ) : isRunning ? (
                        <div className="w-5 h-5 rounded-full border-2 border-primary border-t-transparent animate-spin" />
                      ) : (
                        <span className="text-sm font-bold">{step.num}</span>
                      )}
                    </div>

                    {/* Step title + summary */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-semibold ${isDone ? 'text-emerald-400' : isRunning ? 'text-primary' : isSkipped ? 'text-zinc-600' : 'text-on-surface'}`}>
                          {step.title}
                        </span>
                        {isSkipped && <span className="text-[9px] font-mono uppercase text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded">skipped</span>}
                      </div>
                      {!isExpanded && !isRunning && (
                        <p className="text-xs text-on-surface-variant mt-0.5 truncate">
                          {step.summary}
                        </p>
                      )}
                    </div>

                    {/* Expand arrow (only when not running pipeline) */}
                    {!isPipeline && !isSkipped && (
                      <span className="material-symbols-outlined text-sm text-zinc-500">{isExpanded ? 'expand_less' : 'expand_more'}</span>
                    )}
                  </div>

                  {/* Running progress bar (inline) */}
                  {isRunning && isPipeline && (
                    <div className="pl-[56px] pr-3 pb-3 space-y-1.5">
                      <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden">
                        <div className="bg-primary h-full transition-all duration-500 shadow-[0_0_8px_rgba(208,188,255,0.4)]"
                          style={{ width: `${step.key === 'download' && isDownloading ? downloadProgress : pipelineProgress}%` }} />
                      </div>
                      <p className="text-[10px] font-mono text-on-surface-variant whitespace-pre-line">{pipelineMessage}</p>
                    </div>
                  )}

                  {/* Expanded config panel */}
                  {isExpanded && !isPipeline && (
                    <div className="ml-[56px] mr-3 mb-4 mt-1 p-4 bg-surface-container-lowest rounded-lg border border-outline-variant/10 space-y-4">
                      {step.key === 'download' && (
                        <p className="text-xs text-on-surface-variant">
                          No configuration needed. Videos are downloaded from Douyin via API with yt-dlp as fallback.
                        </p>
                      )}

                      {step.key === 'transcribe' && (
                        <div className="space-y-2">
                          <div>
                            <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block mb-1.5">Method</label>
                            <div className="flex items-center h-10 px-4 bg-surface-container rounded-lg text-xs text-on-surface w-fit">
                              <span className="material-symbols-outlined text-sm mr-2 text-primary">document_scanner</span>
                              OCR via PaddleOCR — auto-detects Chinese subtitles
                            </div>
                          </div>
                        </div>
                      )}

                      {step.key === 'translate' && (
                        <div className="space-y-3">
                          <div>
                            <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block mb-1.5">Translation Profile</label>
                            <select value={selectedProfile} onChange={(e) => setSelectedProfile(e.target.value)}
                              className="w-full bg-surface-container border-none text-xs text-on-surface h-10 px-3 rounded-lg focus:ring-1 focus:ring-primary">
                              <option value="">Skip translation</option>
                              {profiles.map((p) => <option key={p.name} value={p.name}>{p.name} ({p.target_language})</option>)}
                            </select>
                          </div>
                          <div className="grid grid-cols-2 gap-3">
                            <div>
                              <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block mb-1.5">LLM Backend</label>
                              <select value={llmBackend} onChange={(e) => {
                                const val = e.target.value; setLlmBackend(val);
                                const m = MODEL_OPTIONS[val]; if (m?.length) { setLlmModel(m[0].value); saveLLMPrefs(val, m[0].value); }
                              }} className="w-full bg-surface-container border-none text-xs text-on-surface h-10 px-3 rounded-lg focus:ring-1 focus:ring-primary">
                                <option value="deepseek">DeepSeek</option>
                                <option value="anthropic">Anthropic</option>
                                <option value="openai">OpenAI</option>
                              </select>
                            </div>
                            <div>
                              <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block mb-1.5">Model</label>
                              <select value={llmModel} onChange={(e) => { setLlmModel(e.target.value); saveLLMPrefs(llmBackend, e.target.value); }}
                                className="w-full bg-surface-container border-none text-xs text-on-surface h-10 px-3 rounded-lg focus:ring-1 focus:ring-primary">
                                {(MODEL_OPTIONS[llmBackend] || []).map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                              </select>
                            </div>
                          </div>
                          {selectedProfile && !llmApiKey && (
                            <div className="flex items-center gap-2 text-amber-400 bg-amber-500/10 p-3 rounded-lg">
                              <span className="material-symbols-outlined text-sm">warning</span>
                              <span className="text-xs">No <strong>{llmBackend}</strong> API key configured</span>
                              <button onClick={() => navigate('/settings#apikeys')} className="text-xs font-bold underline ml-auto">Settings</button>
                            </div>
                          )}
                        </div>
                      )}

                      {step.key === 'tts' && (
                        <div className="space-y-3">
                          <div className="grid grid-cols-2 gap-3">
                            <div>
                              <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block mb-1.5">Provider</label>
                              <select value={selectedTtsProvider} onChange={(e) => { setSelectedTtsProvider(e.target.value); storageSet('tts_selected_provider', e.target.value); }}
                                className="w-full bg-surface-container border-none text-xs text-on-surface h-10 px-3 rounded-lg focus:ring-1 focus:ring-primary">
                                {ttsProviders.map((p) => <option key={p.id} value={p.id}>{p.name}{p.free ? ' (Free)' : ''}</option>)}
                              </select>
                            </div>
                            <div>
                              <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block mb-1.5">Voice Profile</label>
                              <select value={selectedTtsProfile} onChange={(e) => setSelectedTtsProfile(e.target.value)}
                                className="w-full bg-surface-container border-none text-xs text-on-surface h-10 px-3 rounded-lg focus:ring-1 focus:ring-primary">
                                {Object.entries(ttsProfiles).map(([name, p]) => (
                                  <option key={name} value={name}>{name} ({p.language})</option>
                                ))}
                              </select>
                            </div>
                          </div>

                          {/* Missing API key warning for paid providers */}
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

                          <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-container">
                            <span className="material-symbols-outlined text-sm text-on-surface-variant">speed</span>
                            <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold flex-1">Dub Playback Speed</label>
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
                          <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-container">
                            <span className="material-symbols-outlined text-sm text-on-surface-variant">graphic_eq</span>
                            <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold flex-1">Original Underlay</label>
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
                          <p className="text-[10px] text-on-surface-variant flex items-center gap-1.5">
                            <span className="material-symbols-outlined text-xs text-primary">info</span>
                            Every dub sentence plays at this speed. Pipeline and Video Studio share the same setting.
                          </p>
                        </div>
                      )}

                      {step.key === 'process' && (
                        <div className="space-y-3">
                          <div className="space-y-2">
                            <div className="flex items-center gap-2 p-3 bg-surface-container rounded-lg">
                              <span className="material-symbols-outlined text-sm text-primary">blur_on</span>
                              <div className="flex-1">
                                <p className="text-xs text-on-surface font-medium">Original Subtitle Removal</p>
                                <p className="text-[10px] text-on-surface-variant">Auto-detects OCR region and blurs original Chinese subtitles before burning translated subs</p>
                              </div>
                              <button
                                onClick={() => setBlurEnabled(!blurEnabled)}
                                className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${blurEnabled ? 'bg-primary' : 'bg-surface-container-highest'}`}
                              >
                                <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${blurEnabled ? 'right-0.5' : 'left-0.5'}`} />
                              </button>
                            </div>
                            <div className="flex items-center gap-2 p-3 bg-surface-container rounded-lg">
                              <span className="material-symbols-outlined text-sm text-primary">subtitles</span>
                              <div>
                                <p className="text-xs text-on-surface font-medium">Subtitle Burn-in</p>
                                <p className="text-[10px] text-on-surface-variant">Burns translated subtitles with auto-matched position and font size</p>
                              </div>
                            </div>
                            <div className="flex items-center gap-2 p-3 bg-surface-container rounded-lg">
                              <span className="material-symbols-outlined text-sm text-primary">devices</span>
                              <div>
                                <p className="text-xs text-on-surface font-medium">Platform Reformat</p>
                                <p className="text-[10px] text-on-surface-variant">Reformats video per platform specs (resolution, bitrate, duration limits)</p>
                              </div>
                            </div>
                          </div>
                          <p className="text-[10px] text-on-surface-variant flex items-center gap-1.5">
                            <span className="material-symbols-outlined text-xs text-primary">info</span>
                            Blur + burn + reformat run in a single ffmpeg pass to avoid double-encoding
                          </p>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Spacer between steps */}
                  {!isLast && !isExpanded && <div className="h-2" />}
                </div>
              );
            })}
          </div>
        </div>

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
