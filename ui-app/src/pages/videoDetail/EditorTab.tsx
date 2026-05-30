import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { VideoPlayer } from '../../components/editor/VideoPlayer';
import { SegmentList } from '../../components/editor/SegmentList';
import { Timeline } from '../../components/editor/Timeline';
import { useVideoPlayer } from '../../hooks/useVideoPlayer';
import { srtTimestampToSeconds, secondsToSrtTimestamp } from '../../utils/srtTime';
import {
  getVideo,
  getSrt,
  putSrt,
  getRawVideoUrl,
  getSrtDownloadUrl,
  postPreviewClip,
  subscribeSSE,
  getProcessedVideoUrl,
  getProxyVideoUrl,
} from '../../api/client';
import type { VideoMetadata, SubtitleSegment, VersionEntry } from '../../api/types';
import { VersionPanel } from '../../components/editor/VersionPanel';

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
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [useProxy, setUseProxy] = useState(true);
  const [videoLoading, setVideoLoading] = useState(true);

  const isDirty = useMemo(
    () => JSON.stringify(segments) !== JSON.stringify(originalSegments),
    [segments, originalSegments],
  );

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

  // --- Save (SRT only) ---
  const handleSave = useCallback(async () => {
    if (!videoId || saving) return;
    setSaving(true);
    setSaveStatus('idle');
    try {
      const res = await putSrt(videoId, { language: activeLang, segments });
      setSegments(res.segments);
      setOriginalSegments(res.segments);
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 3000);
    } catch {
      setSaveStatus('error');
    } finally {
      setSaving(false);
    }
  }, [videoId, activeLang, segments, saving]);

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
  }, [videoId, activeLang, segments, isDirty, playerState.currentTime, previewLoading]);

  if (!videoId) return <div className="p-6 text-on-surface">No video ID</div>;

  const videoSrc = video
    ? (useProxy ? getProxyVideoUrl(videoId) : getRawVideoUrl(videoId))
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

            <a
              href={getRawVideoUrl(videoId)}
              download={`${videoId}.mp4`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-container-highest text-on-surface-variant hover:bg-surface-container-high transition-colors"
              title="Download original Douyin video"
            >
              <span className="material-symbols-outlined text-sm">download</span>
              Video
            </a>

            {activeLang && (
              <a
                href={getSrtDownloadUrl(videoId, activeLang)}
                download={`${videoId}_${activeLang}.srt`}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-container-highest text-on-surface-variant hover:bg-surface-container-high transition-colors"
                title={`Download ${activeLang.toUpperCase()} subtitles (working draft)`}
              >
                <span className="material-symbols-outlined text-sm">download</span>
                SRT
              </a>
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
            />

            <Timeline
              segments={segments}
              currentTime={playerState.currentTime}
              duration={playerState.duration}
              onSeek={playerControls.seek}
              onResizeSegment={handleTimelineResize}
            />
          </div>

          {/* Right: Segments (40%) */}
          <div className="w-[40%] flex flex-col border-l border-outline-variant/10 overflow-hidden">
            {/* Header */}
            <div className="flex border-b border-outline-variant/10 px-4 py-2.5 items-center">
              <span className="text-xs font-medium text-on-surface">Segments</span>
              <div className="flex-1" />
              <span className="font-mono text-[9px] text-on-surface-variant">
                {segments.length} segments
              </span>
            </div>

            {/* Segment list */}
            <div className="flex-1 overflow-hidden p-4 flex flex-col">
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
