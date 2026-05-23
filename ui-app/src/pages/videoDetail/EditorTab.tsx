import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { VideoPlayer } from '../../components/editor/VideoPlayer';
import { SubtitleOverlay } from '../../components/editor/SubtitleOverlay';
import type { SubtitleStyle } from '../../components/editor/SubtitleOverlay';
import { SegmentList } from '../../components/editor/SegmentList';
import { Timeline } from '../../components/editor/Timeline';
import { StylePanel } from '../../components/editor/StylePanel';
import { useVideoPlayer } from '../../hooks/useVideoPlayer';
import { srtTimestampToSeconds, secondsToSrtTimestamp } from '../../utils/srtTime';
import {
  getVideo,
  getSrt,
  putSrt,
  getRawVideoUrl,
  postPreviewClip,
  subscribeSSE,
  getProcessedVideoUrl,
  getProxyVideoUrl,
  getPreviewMixUrl,
  getVideoStyle,
  putVideoStyle,
  putSubtitleStyleDefault,
  postDubSync,
} from '../../api/client';
import { storageGet, loadApiKeys, loadLLMPrefs } from '../../utils/storage';
import type { VideoMetadata, SubtitleSegment } from '../../api/types';

type RightTab = 'segments' | 'style';

interface Props {
  videoId: string;
  initialVideo?: VideoMetadata;
  onSyncComplete?: () => void;
}

export function EditorTab({ videoId, initialVideo, onSyncComplete }: Props) {
  // Video player
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playerState, playerControls] = useVideoPlayer(videoRef);

  // Data
  const [video, setVideo] = useState<VideoMetadata | null>(initialVideo ?? null);
  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [originalSegments, setOriginalSegments] = useState<SubtitleSegment[]>([]);
  const [availableLangs, setAvailableLangs] = useState<string[]>(
    initialVideo?.srt_languages ?? [],
  );
  const [activeLang, setActiveLang] = useState<string>('');

  // UI state
  const [rightTab, setRightTab] = useState<RightTab>('segments');
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [useProxy, setUseProxy] = useState(true);
  const [videoLoading, setVideoLoading] = useState(true);

  // Sync-Dub state
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState({ pct: 0, message: '' });
  const [syncError, setSyncError] = useState<string>('');

  // Style
  const [style, setStyle] = useState<SubtitleStyle>({
    fontName: 'Arial',
    fontSize: 24,
    outlineWidth: 2,
    marginV: 30,
    marginH: 0,
    bold: true,
    shadow: true,
    backgroundColor: '',
    backgroundOpacity: 0,
  });
  const [originalStyle, setOriginalStyle] = useState<SubtitleStyle | null>(null);
  const [styleSaving, setStyleSaving] = useState(false);
  const [styleSaveStatus, setStyleSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');

  const isDirty = useMemo(
    () =>
      JSON.stringify(segments) !== JSON.stringify(originalSegments) ||
      (originalStyle !== null && JSON.stringify(style) !== JSON.stringify(originalStyle)),
    [segments, originalSegments, style, originalStyle],
  );

  // Load per-video style (falls back to global default on backend)
  useEffect(() => {
    if (!videoId) return;
    getVideoStyle(videoId)
      .then(({ style: d }) => {
        if (d) {
          const loaded: SubtitleStyle = {
            fontName: (d.font_name as string) || 'Arial',
            fontSize: (d.font_size as number) || 24,
            outlineWidth: (d.outline_width as number) ?? 2,
            marginV: (d.margin_v as number) ?? 30,
            marginH: (d.margin_h as number) ?? 0,
            bold: d.bold !== undefined ? Boolean(d.bold) : true,
            shadow: d.shadow_depth !== undefined ? Number(d.shadow_depth) > 0 : true,
            backgroundColor: (d.background_color as string) || '',
            backgroundOpacity: (d.background_opacity as number) ?? 0,
          };
          setStyle(loaded);
          setOriginalStyle(loaded);
        }
      })
      .catch(() => {});
  }, [videoId]);

  // Refresh video metadata. `initialVideo` seeds the state synchronously so the
  // editor renders immediately; this effect picks up any server-side changes.
  useEffect(() => {
    if (!videoId) return;
    getVideo(videoId)
      .then((v) => {
        setVideo(v);
        setAvailableLangs(v.srt_languages);
      })
      .catch(() => {});
  }, [videoId]);

  // Default-language selection: prefer languages with a `dubsync.srt` on disk
  // (vi > en), fall back to first non-Chinese SRT, then any SRT.
  useEffect(() => {
    if (activeLang) return; // user already chose
    if (!video) return;

    // Priority 1: language with a dubsync.srt (preferring vi over en)
    const dubLangs = (video.dub_status ?? []).map((d) => d.language);
    for (const candidate of ['vi', 'en']) {
      if (dubLangs.includes(candidate)) {
        setActiveLang(candidate);
        return;
      }
    }
    if (dubLangs.length > 0) {
      setActiveLang(dubLangs[0]);
      return;
    }

    // Priority 2: first non-Chinese SRT language
    const nonZh = (video.srt_languages ?? []).filter((l) => l !== 'zh');
    if (nonZh.length > 0) {
      setActiveLang(nonZh[0]);
      return;
    }

    // Priority 3: any SRT language (including zh)
    if (video.srt_languages.length > 0) {
      setActiveLang(video.srt_languages[0]);
    }
  }, [video, activeLang]);

  useEffect(() => {
    if (!videoId || !activeLang) return;

    getSrt(videoId, activeLang)
      .then((res) => {
        setSegments(res.segments);
        setOriginalSegments(res.segments);
      })
      .catch(() => {
        setSegments([]);
        setOriginalSegments([]);
      });
  }, [videoId, activeLang]);

  // --- Segment handlers ---

  const handleUpdateSegment = useCallback((index: number, updated: SubtitleSegment) => {
    setSegments((prev) => prev.map((s, i) => (i === index ? updated : s)));
  }, []);

  const handleDeleteSegment = useCallback((index: number) => {
    setSegments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleSplitSegment = useCallback(
    (index: number, splitTime: number) => {
      setSegments((prev) => {
        const seg = prev[index];
        const start = srtTimestampToSeconds(seg.startTime);
        const end = srtTimestampToSeconds(seg.endTime);

        if (splitTime <= start || splitTime >= end) return prev;

        // Split text at nearest word boundary
        const words = seg.text.split(/\s+/);
        const ratio = (splitTime - start) / (end - start);
        const splitIdx = Math.max(1, Math.round(words.length * ratio));
        const text1 = words.slice(0, splitIdx).join(' ');
        const text2 = words.slice(splitIdx).join(' ') || '...';

        const seg1: SubtitleSegment = {
          ...seg,
          endTime: secondsToSrtTimestamp(splitTime),
          text: text1,
        };
        const seg2: SubtitleSegment = {
          id: Date.now(),
          startTime: secondsToSrtTimestamp(splitTime),
          endTime: seg.endTime,
          text: text2,
        };

        const next = [...prev];
        next.splice(index, 1, seg1, seg2);
        return next;
      });
    },
    [],
  );

  const handleMergeSegment = useCallback((index: number) => {
    setSegments((prev) => {
      if (index >= prev.length - 1) return prev;
      const curr = prev[index];
      const next = prev[index + 1];
      const merged: SubtitleSegment = {
        ...curr,
        endTime: next.endTime,
        text: `${curr.text}\n${next.text}`,
      };
      const result = [...prev];
      result.splice(index, 2, merged);
      return result;
    });
  }, []);

  const handleAddSegment = useCallback(
    (afterIndex: number) => {
      setSegments((prev) => {
        const afterSeg = prev[afterIndex];
        const afterEnd = srtTimestampToSeconds(afterSeg.endTime);
        const nextStart = afterIndex + 1 < prev.length
          ? srtTimestampToSeconds(prev[afterIndex + 1].startTime)
          : afterEnd + 2;
        const gap = nextStart - afterEnd;
        const newStart = afterEnd + 0.1;
        const newEnd = afterEnd + Math.min(gap, 2);

        const newSeg: SubtitleSegment = {
          id: Date.now(),
          startTime: secondsToSrtTimestamp(newStart),
          endTime: secondsToSrtTimestamp(newEnd),
          text: '',
        };
        const result = [...prev];
        result.splice(afterIndex + 1, 0, newSeg);
        return result;
      });
    },
    [],
  );

  const handleTimelineResize = useCallback(
    (index: number, field: 'startTime' | 'endTime', newTime: number) => {
      setSegments((prev) =>
        prev.map((seg, i) =>
          i === index ? { ...seg, [field]: secondsToSrtTimestamp(newTime) } : seg,
        ),
      );
    },
    [],
  );

  const handleDragPosition = useCallback((marginH: number, marginV: number) => {
    setStyle((prev) => ({ ...prev, marginH, marginV }));
  }, []);

  // --- Style payload helper ---
  const stylePayload = useCallback(() => ({
    font_name: style.fontName,
    font_size: style.fontSize,
    outline_width: style.outlineWidth,
    margin_v: style.marginV,
    margin_h: style.marginH,
    bold: style.bold,
    shadow_depth: style.shadow ? 1 : 0,
    background_opacity: style.backgroundOpacity,
  }), [style]);

  // --- Save (subtitles + style) ---
  const handleSave = useCallback(async () => {
    if (!videoId || saving) return;
    setSaving(true);
    setSaveStatus('idle');
    try {
      const [res] = await Promise.all([
        putSrt(videoId, { language: activeLang, segments }),
        putVideoStyle(videoId, stylePayload()),
      ]);
      setSegments(res.segments);
      setOriginalSegments(res.segments);
      setOriginalStyle({ ...style });
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 3000);
    } catch {
      setSaveStatus('error');
    } finally {
      setSaving(false);
    }
  }, [videoId, activeLang, segments, saving, stylePayload, style]);

  const handleSaveAsDefault = useCallback(async () => {
    if (styleSaving) return;
    setStyleSaving(true);
    setStyleSaveStatus('idle');
    try {
      await putSubtitleStyleDefault(stylePayload());
      setStyleSaveStatus('saved');
      setTimeout(() => setStyleSaveStatus('idle'), 3000);
    } catch {
      setStyleSaveStatus('error');
    } finally {
      setStyleSaving(false);
    }
  }, [styleSaving, stylePayload]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't capture when typing in inputs/textareas
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      switch (e.key) {
        case ' ':
        case 'k':
          e.preventDefault();
          playerControls.togglePlay();
          break;
        case 'j':
          e.preventDefault();
          playerControls.seek(playerState.currentTime - 5);
          break;
        case 'l':
          e.preventDefault();
          playerControls.seek(playerState.currentTime + 5);
          break;
        case 'ArrowLeft':
          e.preventDefault();
          playerControls.stepFrame(-1);
          break;
        case 'ArrowRight':
          e.preventDefault();
          playerControls.stepFrame(1);
          break;
      }

      // Ctrl/Cmd+S to save
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [playerControls, playerState.currentTime, handleSave]);

  // --- Sync-Dub ---

  const dubStatusForActive = (video?.dub_status ?? []).find(
    (d) => d.language === activeLang,
  );
  const isOutOfSync = Boolean(dubStatusForActive?.out_of_sync);

  const handleSyncDub = useCallback(async () => {
    if (!video || !activeLang) return;
    setSyncError('');
    setIsSyncing(true);
    setSyncProgress({ pct: 0, message: 'Starting sync…' });

    const provider = storageGet('tts_selected_provider') || 'google';
    const voiceId = storageGet(`tts_voice_id_${provider}`) || '';
    const playbackSpeed = parseFloat(storageGet('tts_playback_speed') || '1.5');
    const underlayDb = parseFloat(storageGet('tts_underlay_db') || '-18');

    const apiKeys = loadApiKeys();
    const apiKey = apiKeys[provider] || undefined;

    const llmPrefs = loadLLMPrefs();
    const llmBackend = llmPrefs.backend;
    const llmApiKey = apiKeys[llmBackend] || undefined;

    try {
      const { task_id } = await postDubSync(video.video_id, {
        language: activeLang,
        provider,
        voice_id: voiceId,
        playback_speed: playbackSpeed,
        underlay_db: underlayDb,
        api_key: apiKey,
        llm_api_key: llmApiKey,
        llm_backend: llmBackend,
      });

      const es = subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') {
          const pct = typeof data.progress === 'number' ? Math.round(data.progress * 100) : 0;
          const msg = typeof data.message === 'string' ? data.message : 'Syncing…';
          setSyncProgress({ pct, message: msg });
        } else if (eventType === 'complete') {
          setIsSyncing(false);
          setSyncProgress({ pct: 100, message: 'Dub synced.' });
          es.close();
          // Refresh the parent's video metadata so dub_status updates and the banner clears
          onSyncComplete?.();
        } else if (eventType === 'error') {
          setIsSyncing(false);
          const errMsg = typeof data.message === 'string' ? data.message : 'Sync failed';
          setSyncError(errMsg);
          es.close();
        }
      });
    } catch (e) {
      setIsSyncing(false);
      setSyncError(e instanceof Error ? e.message : 'Sync failed');
    }
  }, [video, activeLang, onSyncComplete]);

  // --- Preview burn-in ---
  const handlePreviewBurnIn = useCallback(async () => {
    if (!videoId || previewLoading) return;
    setPreviewLoading(true);
    setPreviewUrl(null);
    try {
      // First save current edits
      if (isDirty) {
        await putSrt(videoId, { language: activeLang, segments });
        setOriginalSegments(segments);
      }

      const stylePayloadInline = {
        font_name: style.fontName,
        font_size: style.fontSize,
        outline_width: style.outlineWidth,
        margin_v: style.marginV,
        margin_h: style.marginH,
        bold: style.bold,
        shadow_depth: style.shadow ? 1 : 0,
        background_opacity: Math.round(style.backgroundOpacity * 2.55), // 0-100% → 0-255
      };

      const { task_id } = await postPreviewClip(videoId, {
        language: activeLang,
        start: Math.max(0, playerState.currentTime - 2),
        duration: 10,
        subtitle_style: stylePayloadInline,
      });

      const es = subscribeSSE(task_id, (eventType) => {
        if (eventType === 'complete') {
          setPreviewUrl(getProcessedVideoUrl(videoId, 'preview'));
          setPreviewLoading(false);
          es.close();
        } else if (eventType === 'error') {
          setPreviewLoading(false);
          es.close();
        }
      });
    } catch {
      setPreviewLoading(false);
    }
  }, [videoId, activeLang, segments, isDirty, style, playerState.currentTime, previewLoading]);

  if (!videoId) return <div className="p-6 text-on-surface">No video ID</div>;

  // Prefer the dub-mixed preview MP4 when the active language has a dub, so
  // users hear the dub (with the original Chinese at underlay_db) instead of
  // the raw original. Falls back to raw / proxy for languages without a dub
  // or when viewing zh.
  const hasDubForActiveLang = (video?.dub_status ?? []).some(
    (d) => d.language === activeLang,
  );
  const videoSrc = video
    ? (hasDubForActiveLang && activeLang && activeLang !== 'zh'
        ? getPreviewMixUrl(videoId, activeLang)
        : (useProxy ? getProxyVideoUrl(videoId) : getRawVideoUrl(videoId)))
    : '';

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-hidden flex flex-col">
        {/* Header with editor toolbar */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-outline-variant/10">
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-semibold text-on-surface">
              Subtitle Editor
            </h1>
            <span className="font-mono text-[9px] text-on-surface-variant bg-surface-container-highest px-1.5 py-0.5 rounded">
              {video?.title || videoId}
            </span>

            {/* Language selector */}
            <select
              value={activeLang}
              onChange={(e) => setActiveLang(e.target.value)}
              className="bg-surface-container-lowest border border-outline-variant/20 text-[11px] rounded px-1.5 py-0.5 text-on-surface"
            >
              {availableLangs.map((l) => (
                <option key={l} value={l}>
                  {l === 'en' ? 'English' : l === 'vi' ? 'Vietnamese' : l === 'zh' ? 'Chinese' : l.toUpperCase()}
                </option>
              ))}
            </select>

            {/* Video quality selector */}
            <select
              value={useProxy ? '360p' : 'full'}
              onChange={(e) => { setUseProxy(e.target.value === '360p'); setVideoLoading(true); }}
              className="bg-surface-container-lowest border border-outline-variant/20 text-[11px] rounded px-1.5 py-0.5 text-on-surface font-mono"
            >
              <option value="360p">360p</option>
              <option value="full">Full Res</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            {isDirty && (
              <span className="font-mono text-[9px] text-amber-400 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                Unsaved changes
              </span>
            )}
            {saveStatus === 'saved' && (
              <span className="font-mono text-[9px] text-emerald-400">Saved</span>
            )}
            {saveStatus === 'error' && (
              <span className="font-mono text-[9px] text-red-400">Save failed</span>
            )}

            <button
              onClick={handlePreviewBurnIn}
              disabled={previewLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-highest hover:bg-surface-container-high text-xs text-on-surface transition-colors disabled:opacity-50"
            >
              <span className="material-symbols-outlined text-sm">
                {previewLoading ? 'progress_activity' : 'preview'}
              </span>
              {previewLoading ? 'Rendering...' : 'Preview Burn-in'}
            </button>

            <button
              onClick={handleSave}
              disabled={!isDirty || saving}
              className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium transition-all ${
                isDirty
                  ? 'bg-primary text-on-primary hover:shadow-lg'
                  : 'bg-surface-container-highest text-on-surface-variant cursor-not-allowed'
              }`}
            >
              <span className="material-symbols-outlined text-sm">
                {saving ? 'progress_activity' : 'save'}
              </span>
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>

        {/* Main content: 2-column layout */}
        <div className="flex-1 overflow-hidden flex">
          {/* Left: Video + Timeline (60%) */}
          <div className="w-[60%] flex flex-col p-4 gap-3 overflow-hidden">
            <VideoPlayer
              ref={videoRef}
              src={videoSrc}
              state={playerState}
              controls={playerControls}
              loading={videoLoading}
              onLoadingChange={setVideoLoading}
            >
              <SubtitleOverlay
                segments={segments}
                currentTime={playerState.currentTime}
                style={style}
                onDragPosition={handleDragPosition}
              />
            </VideoPlayer>

            <Timeline
              segments={segments}
              currentTime={playerState.currentTime}
              duration={playerState.duration}
              onSeek={playerControls.seek}
              onResizeSegment={handleTimelineResize}
            />
          </div>

          {/* Right: Tabs (segments / style) (40%) */}
          <div className="w-[40%] flex flex-col border-l border-outline-variant/10 overflow-hidden">
            {/* Tab bar */}
            <div className="flex border-b border-outline-variant/10 px-4">
              {(['segments', 'style'] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setRightTab(tab)}
                  className={`px-4 py-2.5 text-xs font-medium capitalize transition-colors border-b-2 ${
                    rightTab === tab
                      ? 'border-primary text-primary'
                      : 'border-transparent text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  {tab}
                </button>
              ))}

              <div className="flex-1" />
              <span className="font-mono text-[9px] text-on-surface-variant self-center">
                {segments.length} segments
              </span>
            </div>

            {/* Sync-Dub banner */}
            <div className="mx-4 mt-3 space-y-2">
              {isOutOfSync && !isSyncing && !syncError && (
                <div className="bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs p-3 rounded-md flex items-center gap-3">
                  <span className="material-symbols-outlined text-sm">sync_problem</span>
                  <span className="flex-1">
                    Dub for <code className="font-mono">{activeLang}</code> is out of sync with current subtitles.
                  </span>
                  <button
                    onClick={handleSyncDub}
                    className="bg-amber-500 text-zinc-900 px-3 py-1.5 rounded font-bold text-[10px] uppercase tracking-wider hover:bg-amber-400 transition-colors"
                  >
                    Sync Dub
                  </button>
                </div>
              )}

              {isSyncing && (
                <div className="bg-amber-500/10 border border-amber-500/30 p-3 rounded-md space-y-1">
                  <div className="flex justify-between text-[10px] font-mono text-amber-300">
                    <span>{syncProgress.message}</span>
                    <span>{syncProgress.pct}%</span>
                  </div>
                  <div className="w-full bg-amber-500/20 h-1.5 rounded-full overflow-hidden">
                    <div className="h-full bg-amber-400 transition-all" style={{ width: `${syncProgress.pct}%` }} />
                  </div>
                </div>
              )}

              {syncError && (
                <div className="bg-red-500/10 border border-red-500/30 text-red-300 text-xs p-3 rounded-md flex items-center gap-2">
                  <span className="material-symbols-outlined text-sm">error</span>
                  <span className="flex-1">Sync failed: {syncError}</span>
                  <button onClick={() => setSyncError('')} className="text-red-300 hover:text-red-200">
                    <span className="material-symbols-outlined text-sm">close</span>
                  </button>
                </div>
              )}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-hidden p-4 flex flex-col">
              {rightTab === 'segments' ? (
                <SegmentList
                  segments={segments}
                  currentTime={playerState.currentTime}
                  onSeek={playerControls.seek}
                  onUpdate={handleUpdateSegment}
                  onDelete={handleDeleteSegment}
                  onSplit={handleSplitSegment}
                  onMerge={handleMergeSegment}
                  onAdd={handleAddSegment}
                />
              ) : (
                <div className="flex-1 overflow-y-auto flex flex-col">
                  <div className="flex-1">
                    <StylePanel style={style} onChange={setStyle} />
                  </div>
                  <div className="pt-3 mt-3 border-t border-outline-variant/10 flex items-center gap-2">
                    <button
                      onClick={handleSaveAsDefault}
                      disabled={styleSaving}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-highest text-on-surface text-xs hover:bg-surface-container-high transition-all disabled:opacity-50"
                      title="Save current style as the default for all new videos"
                    >
                      <span className="material-symbols-outlined text-sm">
                        {styleSaving ? 'progress_activity' : 'bookmark'}
                      </span>
                      {styleSaving ? 'Saving...' : 'Save as Default'}
                    </button>
                    {styleSaveStatus === 'saved' && (
                      <span className="font-mono text-[9px] text-emerald-400">Saved</span>
                    )}
                    {styleSaveStatus === 'error' && (
                      <span className="font-mono text-[9px] text-red-400">Failed</span>
                    )}
                    <span className="font-mono text-[8px] text-on-surface-variant ml-auto">
                      Save button saves style for this video
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Preview modal */}
        {previewUrl && (
          <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-8">
            <div className="bg-surface-container rounded-xl border border-outline-variant/10 max-w-2xl w-full overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant/10">
                <span className="text-sm font-medium text-on-surface">Burn-in Preview</span>
                <button onClick={() => setPreviewUrl(null)} className="text-on-surface-variant hover:text-on-surface">
                  <span className="material-symbols-outlined">close</span>
                </button>
              </div>
              <div className="p-4">
                <video
                  controls
                  autoPlay
                  className="w-full rounded-lg bg-black"
                  src={previewUrl}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
