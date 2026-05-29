import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { VideoPlayer } from '../../components/editor/VideoPlayer';
import { SubtitleRenderer } from '../../components/editor/SubtitleRenderer';
import { SegmentList } from '../../components/editor/SegmentList';
import { Timeline } from '../../components/editor/Timeline';
import { StylePanel } from '../../components/editor/StylePanel';
import { useVideoPlayer } from '../../hooks/useVideoPlayer';
import { srtTimestampToSeconds, secondsToSrtTimestamp } from '../../utils/srtTime';
import { diffSpec } from '../../utils/diffSpec';
import {
  getVideo,
  getSrt,
  putSrt,
  getRawVideoUrl,
  postPreviewClip,
  subscribeSSE,
  getProcessedVideoUrl,
  getProxyVideoUrl,
  getVideoStyle,
  putVideoStyle,
  putSubtitleStyleDefault,
  deleteVideoStyle,
  getSubtitleStyleDefault,
  getSubtitleRegion,
} from '../../api/client';
import type { VideoMetadata, SubtitleSegment, SubtitleRegion, VersionEntry } from '../../api/types';
import type { SubtitleStyleSpec } from '../../api/types';
import { VersionPanel } from '../../components/editor/VersionPanel';

type RightTab = 'segments' | 'style';

interface Props {
  videoId: string;
  initialVideo?: VideoMetadata;
  onSyncComplete?: () => void;
  versions: VersionEntry[];
  onCreateSnapshot: (name: string | null) => Promise<void>;
  onRenameVersion: (versionId: string, name: string | null) => Promise<void>;
  onDeleteVersion: (versionId: string) => Promise<void>;
  activeLang: string;
  onActiveLangChange: (lang: string) => void;
}

export function EditorTab({ videoId, initialVideo, versions, onCreateSnapshot, onRenameVersion, onDeleteVersion, activeLang, onActiveLangChange }: Props) {
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

  // UI state
  const [rightTab, setRightTab] = useState<RightTab>('segments');
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [useProxy, setUseProxy] = useState(true);
  const [videoLoading, setVideoLoading] = useState(true);

  // Subtitle style — new nested spec model
  const [globalDefault, setGlobalDefault] = useState<SubtitleStyleSpec | null>(null);
  const [savedSpec, setSavedSpec] = useState<SubtitleStyleSpec | null>(null);
  const [draftSpec, setDraftSpec] = useState<SubtitleStyleSpec | null>(null);

  const [styleSaving, setStyleSaving] = useState(false);
  const [styleSaveStatus, setStyleSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');

  // Subtitle region (for OCR re-align)
  const [subtitleRegion, setSubtitleRegion] = useState<SubtitleRegion | null>(null);

  // Video rect for SubtitleRenderer overlay positioning
  const [videoRect, setVideoRect] = useState<{
    offsetX: number;
    offsetY: number;
    width: number;
    height: number;
  } | undefined>(undefined);

  const isDirty = useMemo(
    () =>
      JSON.stringify(segments) !== JSON.stringify(originalSegments) ||
      (savedSpec !== null && JSON.stringify(draftSpec) !== JSON.stringify(savedSpec)),
    [segments, originalSegments, draftSpec, savedSpec],
  );

  // On mount: load global default + per-video merged style in parallel
  useEffect(() => {
    if (!videoId) return;
    Promise.all([getSubtitleStyleDefault(), getVideoStyle(videoId)])
      .then(([globalSpec, videoRes]) => {
        setGlobalDefault(globalSpec);
        setSavedSpec(videoRes.style);
        setDraftSpec(structuredClone(videoRes.style));
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

  // Default-language selection: fall back to first non-Chinese SRT, then any SRT.
  useEffect(() => {
    if (activeLang) return; // user already chose (or parent already set a value)
    if (!video) return;

    // Priority 1: first non-Chinese SRT language
    const nonZh = (video.srt_languages ?? []).filter((l) => l !== 'zh');
    if (nonZh.length > 0) {
      onActiveLangChange(nonZh[0]);
      return;
    }

    // Priority 2: any SRT language (including zh)
    if (video.srt_languages.length > 0) {
      onActiveLangChange(video.srt_languages[0]);
    }
  }, [video, activeLang, onActiveLangChange]);

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

  // Track video element rect for subtitle overlay positioning
  useEffect(() => {
    const videoEl = videoRef.current;
    if (!videoEl) return;
    const container = videoEl.parentElement;
    if (!container) return;

    const update = () => {
      const containerRect = container.getBoundingClientRect();
      const vidRect = videoEl.getBoundingClientRect();
      setVideoRect({
        offsetX: vidRect.left - containerRect.left,
        offsetY: vidRect.top - containerRect.top,
        width: vidRect.width,
        height: vidRect.height,
      });
    };

    update();
    const ro = new ResizeObserver(update);
    ro.observe(videoEl);
    ro.observe(container);
    return () => ro.disconnect();
  }, []);

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
        let newStart: number;
        let newEnd: number;
        let insertAt: number;

        if (afterIndex < 0 || prev.length === 0) {
          // Empty-list case: insert a row at t=0 with up to 2s duration.
          newStart = 0;
          const cap = playerState.duration > 0 ? playerState.duration : 2;
          newEnd = Math.min(2, cap);
          insertAt = 0;
        } else {
          const afterSeg = prev[afterIndex];
          const afterEnd = srtTimestampToSeconds(afterSeg.endTime);
          const nextStart = afterIndex + 1 < prev.length
            ? srtTimestampToSeconds(prev[afterIndex + 1].startTime)
            : afterEnd + 2;
          const gap = nextStart - afterEnd;
          newStart = afterEnd + 0.1;
          newEnd = afterEnd + Math.min(gap, 2);
          insertAt = afterIndex + 1;
        }

        const newSeg: SubtitleSegment = {
          id: Date.now(),
          startTime: secondsToSrtTimestamp(newStart),
          endTime: secondsToSrtTimestamp(newEnd),
          text: '',
        };
        const result = [...prev];
        result.splice(insertAt, 0, newSeg);
        return result;
      });
    },
    [playerState.duration],
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

  // --- Save (subtitles + style delta) ---
  const handleSave = useCallback(async () => {
    if (!videoId || saving || !draftSpec || !globalDefault) return;
    setSaving(true);
    setSaveStatus('idle');
    try {
      const delta = diffSpec(draftSpec, globalDefault);
      const [res] = await Promise.all([
        putSrt(videoId, { language: activeLang, segments }),
        putVideoStyle(videoId, delta),
      ]);
      setSegments(res.segments);
      setOriginalSegments(res.segments);
      setSavedSpec(structuredClone(draftSpec));
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 3000);
    } catch {
      setSaveStatus('error');
    } finally {
      setSaving(false);
    }
  }, [videoId, activeLang, segments, saving, draftSpec, globalDefault]);

  const handleSaveAsDefault = useCallback(async () => {
    if (styleSaving || !draftSpec) return;
    setStyleSaving(true);
    setStyleSaveStatus('idle');
    try {
      const next = await putSubtitleStyleDefault(draftSpec);
      setGlobalDefault(next);
      setStyleSaveStatus('saved');
      setTimeout(() => setStyleSaveStatus('idle'), 3000);
    } catch {
      setStyleSaveStatus('error');
    } finally {
      setStyleSaving(false);
    }
  }, [styleSaving, draftSpec]);

  const handleResetToGlobal = useCallback(async () => {
    if (!videoId || !globalDefault) return;
    if (!confirm('Reset all per-video style overrides? This clears every customization for this video.')) return;
    const res = await deleteVideoStyle(videoId);
    setSavedSpec(res.style);
    setDraftSpec(structuredClone(res.style));
  }, [videoId, globalDefault]);

  const handleRealignToOcr = useCallback(async () => {
    if (!videoId || !draftSpec || !globalDefault) return;
    if (!confirm('Re-align subtitle position to the OCR-detected region? Your current vertical/horizontal/alignment values will be lost.')) return;
    const delta = diffSpec(draftSpec, globalDefault);
    delete (delta as Record<string, unknown>).position;
    const res = await putVideoStyle(videoId, delta);
    setSavedSpec(res.style);
    setDraftSpec(structuredClone(res.style));
  }, [videoId, draftSpec, globalDefault]);

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

      const { task_id } = await postPreviewClip(videoId, {
        language: activeLang,
        start: Math.max(0, playerState.currentTime - 2),
        duration: 10,
        subtitle_style: draftSpec ?? undefined,
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
  }, [videoId, activeLang, segments, isDirty, draftSpec, playerState.currentTime, previewLoading]);

  // Load subtitle region on mount (best-effort) so hasOcrRegion is accurate.
  useEffect(() => {
    if (!videoId) return;
    getSubtitleRegion(videoId)
      .then((r) => setSubtitleRegion(r))
      .catch(() => {});
  }, [videoId]);

  if (!videoId) return <div className="p-6 text-on-surface">No video ID</div>;

  const videoSrc = video
    ? (useProxy ? getProxyVideoUrl(videoId) : getRawVideoUrl(videoId))
    : '';

  // Source dimensions for StylePanel — VideoMetadata has no width/height fields;
  // fall back to portrait defaults (1080×1920) which match the Douyin format.
  const sourceW = 1080;
  const sourceH = 1920;

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
              onChange={(e) => onActiveLangChange(e.target.value)}
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

            <button
              onClick={async () => {
                if (saving) return;
                if (isDirty) {
                  // Ensure the working draft is up to date before snapshotting.
                  await handleSave();
                }
                await onCreateSnapshot(null);
              }}
              disabled={saving || segments.length === 0}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium bg-secondary/20 text-secondary hover:bg-secondary/30 transition-colors disabled:opacity-50"
              title="Save current draft as the next auto-numbered version"
            >
              <span className="material-symbols-outlined text-sm">bookmark_add</span>
              Save as version
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
              {draftSpec && (
                <SubtitleRenderer
                  segments={segments}
                  currentTime={playerState.currentTime}
                  spec={draftSpec}
                  onDragPosition={(mh, mv) =>
                    setDraftSpec((s) => s ? { ...s, position: { ...s.position, margin_h: mh, margin_v: mv } } : s)
                  }
                  videoRect={videoRect}
                />
              )}
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
                    {draftSpec && (
                      <StylePanel
                        spec={draftSpec}
                        onChange={setDraftSpec}
                        sourceW={sourceW}
                        sourceH={sourceH}
                        hasOcrRegion={!!subtitleRegion}
                        onRealignToOcr={handleRealignToOcr}
                      />
                    )}
                  </div>
                  <div className="pt-3 mt-3 border-t border-outline-variant/10 flex items-center gap-2 flex-wrap">
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
                    <button
                      onClick={handleResetToGlobal}
                      disabled={!globalDefault}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-highest text-on-surface text-xs hover:bg-surface-container-high transition-all disabled:opacity-50"
                      title="Reset all per-video style overrides to the global default"
                    >
                      <span className="material-symbols-outlined text-sm">restart_alt</span>
                      Reset to Default
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

            <div className="px-4 pb-4">
              <VersionPanel
                versions={versions}
                onRename={(id, name) => onRenameVersion(id, name)}
                onDelete={(id) => {
                  if (confirm(`Delete ${id}? This also deletes any dub WAVs generated from this version.`)) {
                    onDeleteVersion(id);
                  }
                }}
              />
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
