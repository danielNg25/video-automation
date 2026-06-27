import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { VideoPlayer } from '../../components/editor/VideoPlayer';
import { SegmentList } from '../../components/editor/SegmentList';
import { SubtitleOverlay } from '../../components/editor/SubtitleOverlay';
import type { SubtitleStyle } from '../../components/editor/SubtitleOverlay';
import { Timeline } from '../../components/editor/Timeline';
import { useVideoPlayer } from '../../hooks/useVideoPlayer';
import { srtTimestampToSeconds, secondsToSrtTimestamp } from '../../utils/srtTime';
import { safeFilename } from '../../utils/filename';
import {
  getVideo,
  getSrt,
  putSrt,
  getRawVideoUrl,
  getSrtDownloadUrl,
  getProxyVideoUrl,
  getTTSList,
  getTTSAudioUrl,
} from '../../api/client';
import type { TTSAudioEntry } from '../../api/client';
import type {
  VideoMetadata,
  SubtitleSegment,
  VersionEntry,
} from '../../api/types';
import { VersionPanel } from '../../components/editor/VersionPanel';
import { DubPanel } from '../../components/editor/DubPanel';

// Plain-text subtitle overlay style. The SubtitleOverlay component supports
// the deleted styling UI's full ASS-spec style, but the refocused app only
// needs a readable preview default.
const DEFAULT_OVERLAY_STYLE: SubtitleStyle = {
  fontName: 'Inter, system-ui, sans-serif',
  fontSize: 96,
  outlineWidth: 4,
  marginV: 80,
  marginH: 0,
  bold: true,
  shadow: true,
  backgroundColor: '#000000',
  backgroundOpacity: 55,
};

// ── Toolbar styling helpers ─────────────────────────────────────────────────
// All controls share h-8 + rounded-lg + the same elevated surface, so the row
// reads as one cohesive strip. Borders are dropped (the elevated bg already
// separates each control from the page background); the focus ring takes over
// when needed. Variants tint the bg subtly without changing dimensions, so
// switching between e.g. neutral and amber doesn't shift adjacent controls.

type ToolbarVariant = 'neutral' | 'amber' | 'primary';

function toolbarSelectClass(variant: ToolbarVariant = 'neutral'): string {
  const tint =
    variant === 'amber'
      ? 'bg-amber-500/15 text-amber-200 ring-1 ring-amber-400/30'
      : variant === 'primary'
        ? 'bg-primary/15 text-primary ring-1 ring-primary/30'
        : 'bg-surface-container-high text-on-surface';
  return `h-8 px-2.5 pr-7 text-xs font-medium rounded-lg border-none appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${tint}`;
}

function toolbarBtnClass(variant: ToolbarVariant = 'neutral'): string {
  const tint =
    variant === 'primary'
      ? 'bg-primary text-on-primary hover:brightness-110 active:scale-[0.98]'
      : variant === 'amber'
        ? 'bg-amber-500/15 text-amber-200 hover:bg-amber-500/25'
        : 'bg-surface-container-high text-on-surface hover:bg-surface-container-highest';
  return `h-8 px-3 inline-flex items-center gap-1.5 text-xs font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${tint}`;
}

interface Props {
  videoId: string;
  initialVideo?: VideoMetadata;
  onSyncComplete?: () => void;
  versions: VersionEntry[];
  onCreateSnapshot: (name: string | null) => Promise<void>;
  onRenameVersion: (versionId: string, name: string | null) => Promise<void>;
  onDeleteVersion: (versionId: string) => Promise<void>;
  onImportVersion: (file: File, name: string | null) => Promise<void>;
  activeLang: string;
  onActiveLangChange: (lang: string) => void;
}

export function EditorTab({ videoId, initialVideo, versions, onCreateSnapshot, onRenameVersion, onDeleteVersion, onImportVersion, activeLang, onActiveLangChange }: Props) {
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  const handleImport = useCallback(async (file: File) => {
    setImporting(true);
    setSaveStatus('idle');
    try {
      await onImportVersion(file, null);
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 3000);
    } catch {
      setSaveStatus('error');
    } finally {
      setImporting(false);
    }
  }, [onImportVersion]);
  const [useProxy, setUseProxy] = useState(true);
  const [videoLoading, setVideoLoading] = useState(true);

  // Preview pickers: which subtitle version is loaded into the editor, and
  // which dub WAV plays alongside the video. 'draft' means the working draft
  // (editable); any other value loads that snapshot read-only. '' for the
  // dub means use the source video's own audio.
  const [previewVersion, setPreviewVersion] = useState<string>('draft');
  const [previewDub, setPreviewDub] = useState<string>('');
  const [dubList, setDubList] = useState<TTSAudioEntry[]>([]);
  const dubAudioRef = useRef<HTMLAudioElement>(null);

  const isPreview = previewVersion !== 'draft';

  const isDirty = useMemo(
    () => JSON.stringify(segments) !== JSON.stringify(originalSegments),
    [segments, originalSegments],
  );

  // Suggested download base — matches the BE's safe_filename() so the
  // `<a download>` attribute agrees with the Content-Disposition header.
  const downloadBase = useMemo(
    () => safeFilename(video?.title, videoId),
    [video?.title, videoId],
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

  // Reset preview pickers when the language changes — version/dub bindings
  // are language-specific (a v1 in 'en' is unrelated to a v1 in 'vi').
  useEffect(() => {
    setPreviewVersion('draft');
    setPreviewDub('');
  }, [activeLang]);

  useEffect(() => {
    if (!videoId || !activeLang) return;

    getSrt(videoId, activeLang, previewVersion)
      .then((res) => {
        setSegments(res.segments);
        setOriginalSegments(res.segments);
      })
      .catch(() => {
        setSegments([]);
        setOriginalSegments([]);
      });
  }, [videoId, activeLang, previewVersion]);

  // Load the dub list for this video and filter to the current language.
  useEffect(() => {
    if (!videoId) return;
    getTTSList(videoId)
      .then(setDubList)
      .catch(() => setDubList([]));
  }, [videoId]);

  const dubsForLang = useMemo(
    () => dubList.filter((d) => d.language === activeLang),
    [dubList, activeLang],
  );

  // Sync the dub <audio> element with the <video>. When a dub is picked, the
  // video is muted and the audio element scrubs/plays/pauses in lockstep.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !!previewDub;
  }, [previewDub]);

  useEffect(() => {
    const a = dubAudioRef.current;
    if (!a) return;
    if (playerState.isPlaying) {
      void a.play().catch(() => {});
    } else {
      a.pause();
    }
  }, [playerState.isPlaying, previewDub]);

  useEffect(() => {
    const a = dubAudioRef.current;
    if (!a) return;
    // Drift correction: if the audio is more than 0.3s out of sync with the
    // video (user seeked, or playback drifted), pull it back into line.
    if (Math.abs(a.currentTime - playerState.currentTime) > 0.3) {
      a.currentTime = playerState.currentTime;
    }
  }, [playerState.currentTime, previewDub]);

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

        if (afterIndex < 0 && prev.length === 0) {
          // Empty-list case: insert a row at t=0 with up to 2s duration.
          newStart = 0;
          const cap = playerState.duration > 0 ? playerState.duration : 2;
          newEnd = Math.min(2, cap);
          insertAt = 0;
        } else if (afterIndex < 0) {
          // Prepend before the current first segment.
          const firstStart = srtTimestampToSeconds(prev[0].startTime);
          newStart = 0;
          const room = firstStart - 0.1;
          newEnd = room > 0.1 ? Math.min(2, room) : Math.min(2, Math.max(0.5, firstStart));
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
      const res = await putSrt(videoId, {
        language: activeLang,
        segments,
        version: previewVersion,
      });
      setSegments(res.segments);
      setOriginalSegments(res.segments);
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 3000);
    } catch {
      setSaveStatus('error');
    } finally {
      setSaving(false);
    }
  }, [videoId, activeLang, segments, saving, previewVersion]);

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
  if (!videoId) return <div className="p-6 text-on-surface">No video ID</div>;

  const videoSrc = video
    ? (useProxy ? getProxyVideoUrl(videoId) : getRawVideoUrl(videoId))
    : '';

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-hidden flex flex-col">
        {/* Preview banner — sits above the 2-column main area when active. */}
        {/* (Original preview banner moved below the main flex declaration.) */}

        {/* Main content: 2-column layout. The toolbar lives INSIDE the left
            column so the right column (segment list) extends up to the same
            top y-line as the selects row — no wasted space to the right of
            the selects. */}
        <div className="flex-1 overflow-hidden flex">
          {/* Left: toolbar + Video + Timeline (60%) */}
          <div className="w-[60%] flex flex-col overflow-hidden">
            {/* Toolbar — two rows: preview selects on top, action buttons below.
                The editable title chip lives in the parent TopBar (see
                VideoDetail.tsx → EditableTitleChip) so it doesn't eat a row
                inside the editor body. */}
            <div className="flex flex-col gap-2 px-6 py-2.5 border-b border-outline-variant/10 shrink-0">
              {/* Row 1 — Preview selects: language / subtitle version / dub.
                  Video quality lives here too — it tunes what you're previewing,
                  not an action you take. */}
              <div className="flex items-center gap-2 flex-wrap">
            <select
              value={activeLang}
              onChange={(e) => onActiveLangChange(e.target.value)}
              className={toolbarSelectClass()}
              aria-label="Subtitle language"
            >
              {availableLangs.map((l) => (
                <option key={l} value={l}>
                  {l === 'en' ? 'English' : l === 'vi' ? 'Vietnamese' : l === 'zh' ? 'Chinese' : l.toUpperCase()}
                </option>
              ))}
            </select>
            <select
              value={previewVersion}
              onChange={(e) => setPreviewVersion(e.target.value)}
              className={`${toolbarSelectClass(isPreview ? 'amber' : 'neutral')} w-44`}
              title={isPreview ? `Editing ${previewVersion} — Save overwrites it` : 'Editing the working draft'}
              aria-label="Subtitle version"
            >
              <option value="draft">Working draft</option>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.id}{v.name ? ` — ${v.name}` : ''}
                </option>
              ))}
            </select>
            <select
              value={previewDub}
              onChange={(e) => setPreviewDub(e.target.value)}
              className={`${toolbarSelectClass(previewDub ? 'primary' : 'neutral')} w-44`}
              disabled={dubsForLang.length === 0}
              title={dubsForLang.length === 0 ? 'No dubs available for this language' : 'Play a generated dub instead of source audio'}
              aria-label="Dub audio"
            >
              <option value="">Source audio</option>
              {dubsForLang.map((d) => (
                <option key={d.filename} value={d.filename}>
                  {d.version} · {d.voice}
                </option>
              ))}
            </select>
            {previewDub && activeLang && (() => {
              const sel = dubsForLang.find((d) => d.filename === previewDub);
              const dubName = sel
                ? `${downloadBase}.${activeLang}.${sel.version}.${sel.voice}.wav`
                : previewDub;
              return (
                <a
                  href={getTTSAudioUrl(videoId, activeLang, previewDub)}
                  download={dubName}
                  className="inline-flex items-center justify-center h-8 w-8 rounded-md text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors"
                  title={`Download ${dubName}`}
                  aria-label="Download selected dub"
                >
                  <span className="material-symbols-outlined text-[18px]">download</span>
                </a>
              );
            })()}
            <select
              value={useProxy ? '360p' : 'full'}
              onChange={(e) => { setUseProxy(e.target.value === '360p'); setVideoLoading(true); }}
              className={toolbarSelectClass()}
              aria-label="Video quality"
            >
              <option value="360p">360p</option>
              <option value="full">Full Res</option>
            </select>
          </div>

          {/* Row 2 — Action buttons + save-status indicator. */}
          <div className="flex items-center gap-2 flex-wrap">
            {(isDirty || saveStatus !== 'idle') && (
              <div className="flex items-center gap-2 pr-3 mr-1 border-r border-outline-variant/15">
                {isDirty && (
                  <span className="font-mono text-[10px] text-amber-400 flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                    Unsaved
                  </span>
                )}
                {saveStatus === 'saved' && (
                  <span className="font-mono text-[10px] text-emerald-400 flex items-center gap-1">
                    <span className="material-symbols-outlined text-sm">check_circle</span>
                    Saved
                  </span>
                )}
                {saveStatus === 'error' && (
                  <span className="font-mono text-[10px] text-red-400 flex items-center gap-1">
                    <span className="material-symbols-outlined text-sm">error</span>
                    Save failed
                  </span>
                )}
              </div>
            )}
            <a
              href={getRawVideoUrl(videoId)}
              download={`${downloadBase}.mp4`}
              className={toolbarBtnClass()}
              title="Download original video"
            >
              <span className="material-symbols-outlined text-[16px]">download</span>
              <span>Video</span>
            </a>
            {activeLang && (
              <a
                href={getSrtDownloadUrl(videoId, activeLang, previewVersion)}
                download={
                  previewVersion === 'draft'
                    ? `${downloadBase}.${activeLang}.srt`
                    : `${downloadBase}.${activeLang}.${previewVersion}.srt`
                }
                className={toolbarBtnClass()}
                title={`Download ${activeLang.toUpperCase()} SRT (${isPreview ? previewVersion : 'working draft'})`}
              >
                <span className="material-symbols-outlined text-[16px]">download</span>
                <span>SRT</span>
              </a>
            )}
            {activeLang && (
              <a
                href={getSrtDownloadUrl(videoId, activeLang, previewVersion, 'txt')}
                download={
                  previewVersion === 'draft'
                    ? `${downloadBase}.${activeLang}.txt`
                    : `${downloadBase}.${activeLang}.${previewVersion}.txt`
                }
                className={toolbarBtnClass()}
                title={`Download ${activeLang.toUpperCase()} as plain text — one subtitle per line, no timestamps (${isPreview ? previewVersion : 'working draft'})`}
              >
                <span className="material-symbols-outlined text-[16px]">description</span>
                <span>TXT</span>
              </a>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".srt"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  handleImport(file);
                }
                e.target.value = '';
              }}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={importing || !activeLang}
              className={toolbarBtnClass('neutral')}
              title={activeLang ? `Upload an edited ${activeLang.toUpperCase()} SRT as a new version` : 'Pick a language first'}
            >
              <span className="material-symbols-outlined text-[16px]">
                {importing ? 'progress_activity' : 'upload'}
              </span>
              <span>{importing ? 'Importing…' : 'Import'}</span>
            </button>
            <button
              onClick={handleSave}
              disabled={!isDirty || saving}
              className={toolbarBtnClass(isDirty ? 'primary' : 'neutral')}
              title={isPreview ? `Save edits back to ${previewVersion}` : 'Save the working draft'}
            >
              <span className="material-symbols-outlined text-[16px]">
                {saving ? 'progress_activity' : 'save'}
              </span>
              <span>{saving ? 'Saving…' : isPreview ? `Save to ${previewVersion}` : 'Save'}</span>
            </button>
            <button
              onClick={async () => {
                if (saving) return;
                if (isDirty) {
                  await handleSave();
                }
                await onCreateSnapshot(null);
              }}
              disabled={saving || segments.length === 0 || isPreview}
              className={toolbarBtnClass('neutral')}
              title={isPreview ? 'Switch to the working draft to snapshot' : 'Save current draft as the next auto-numbered version'}
            >
              <span className="material-symbols-outlined text-[16px]">bookmark_add</span>
              <span>Save as version</span>
            </button>
          </div>
        </div>

            {/* Preview banner — scoped to the left column so it doesn't push
                the segment list down on the right. */}
            {isPreview && (
              <div className="flex items-center gap-2 px-6 py-1.5 bg-amber-500/10 border-b border-amber-400/20 text-[11px] text-amber-300 shrink-0">
                <span className="material-symbols-outlined text-sm">edit_note</span>
                Editing <span className="font-mono font-semibold">{previewVersion}</span> — Save will overwrite this version in place.
                <button
                  type="button"
                  onClick={() => setPreviewVersion('draft')}
                  className="ml-auto underline hover:text-amber-200"
                >
                  Switch to working draft
                </button>
              </div>
            )}

            {/* Video + timeline — fills the remaining height of the left column. */}
            <div className="flex-1 flex flex-col p-4 gap-3 overflow-hidden">
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
                  style={DEFAULT_OVERLAY_STYLE}
                />
              </VideoPlayer>

              {/* Hidden synced dub audio. The <video> element is muted whenever a
                  dub is selected; this element plays/pauses/seeks in lockstep. */}
              <audio
                ref={dubAudioRef}
                src={previewDub && activeLang ? getTTSAudioUrl(videoId, activeLang, previewDub) : undefined}
                preload="auto"
                className="hidden"
              />

              <Timeline
                segments={segments}
                currentTime={playerState.currentTime}
                duration={playerState.duration}
                onSeek={playerControls.seek}
                onResizeSegment={handleTimelineResize}
              />
            </div>
          </div>

          {/* Right: Segments (40%) — the "Segments" header was removed so the
              list aligns vertically with the version/dub pickers on the left. */}
          <div className="w-[40%] flex flex-col border-l border-outline-variant/10 overflow-hidden">
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
                buildDownloadUrl={(id) =>
                  activeLang ? getSrtDownloadUrl(videoId, activeLang, id) : null
                }
              />
              <DubPanel
                dubs={dubsForLang}
                buildDownloadUrl={(filename) =>
                  activeLang ? getTTSAudioUrl(videoId, activeLang, filename) : null
                }
              />
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
