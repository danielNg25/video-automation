import { useState, useEffect, useCallback, useMemo } from 'react';
import { SegmentList } from './editor/SegmentList';
import { srtTimestampToSeconds, secondsToSrtTimestamp } from '../utils/srtTime';
import {
  getSrt, putSrt, postExportPreview, postExport, getExportedVideoUrl,
  subscribeSSE,
} from '../api/client';
import type { TTSAudioEntry } from '../api/client';
import type { SubtitleSegment } from '../api/types';

interface SubtitleEditorPanelProps {
  videoId: string;
  srtLanguages: string[];
  defaultLang?: string;
  ttsList: TTSAudioEntry[];
  onExportDone?: () => void;
}

export function SubtitleEditorPanel({ videoId, srtLanguages, defaultLang, ttsList, onExportDone }: SubtitleEditorPanelProps) {
  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [originalSegments, setOriginalSegments] = useState<SubtitleSegment[]>([]);
  const [activeLang, setActiveLang] = useState(defaultLang || srtLanguages.find(l => l !== 'zh') || srtLanguages[0] || 'vi');
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');

  // Preview / Export controls
  const [selectedTtsFile, setSelectedTtsFile] = useState<string | null>(null);
  const [videoVol, setVideoVol] = useState(30);
  const [dubVol, setDubVol] = useState(100);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState('');

  // Export
  const [isExporting, setIsExporting] = useState(false);
  const [exportProgress, setExportProgress] = useState({ pct: 0, message: '' });
  const [exportError, setExportError] = useState('');
  const [exportDone, setExportDone] = useState(false);

  const isDirty = useMemo(
    () => JSON.stringify(segments) !== JSON.stringify(originalSegments),
    [segments, originalSegments],
  );

  // Auto-select first TTS file
  useEffect(() => {
    if (ttsList.length > 0 && !selectedTtsFile) {
      setSelectedTtsFile(ttsList[0].filename);
    }
  }, [ttsList, selectedTtsFile]);

  // Load SRT
  useEffect(() => {
    getSrt(videoId, activeLang)
      .then(res => { setSegments(res.segments); setOriginalSegments(res.segments); })
      .catch(() => { setSegments([]); setOriginalSegments([]); });
  }, [videoId, activeLang]);

  // Segment handlers
  const handleUpdateSegment = useCallback((index: number, updated: SubtitleSegment) => {
    setSegments(prev => prev.map((s, i) => i === index ? updated : s));
  }, []);

  const handleDeleteSegment = useCallback((index: number) => {
    setSegments(prev => prev.filter((_, i) => i !== index));
  }, []);

  const handleSplitSegment = useCallback((index: number, splitTime: number) => {
    setSegments(prev => {
      const seg = prev[index];
      const start = srtTimestampToSeconds(seg.startTime);
      const end = srtTimestampToSeconds(seg.endTime);
      if (splitTime <= start || splitTime >= end) return prev;
      const words = seg.text.split(/\s+/);
      const ratio = (splitTime - start) / (end - start);
      const splitIdx = Math.max(1, Math.round(words.length * ratio));
      const text1 = words.slice(0, splitIdx).join(' ');
      const text2 = words.slice(splitIdx).join(' ') || '...';
      const next = [...prev];
      next.splice(index, 1,
        { ...seg, id: seg.id, endTime: secondsToSrtTimestamp(splitTime), text: text1 },
        { ...seg, id: seg.id + 0.5, startTime: secondsToSrtTimestamp(splitTime), text: text2 },
      );
      return next.map((s, i) => ({ ...s, id: i + 1 }));
    });
  }, []);

  const handleMergeSegment = useCallback((index: number) => {
    setSegments(prev => {
      if (index >= prev.length - 1) return prev;
      const a = prev[index], b = prev[index + 1];
      const merged = { ...a, endTime: b.endTime, text: `${a.text} ${b.text}` };
      const next = [...prev];
      next.splice(index, 2, merged);
      return next.map((s, i) => ({ ...s, id: i + 1 }));
    });
  }, []);

  const handleAddSegment = useCallback(() => {
    const lastEnd = segments.length > 0
      ? srtTimestampToSeconds(segments[segments.length - 1].endTime) : 0;
    setSegments(prev => [...prev, {
      id: prev.length + 1,
      startTime: secondsToSrtTimestamp(lastEnd + 0.5),
      endTime: secondsToSrtTimestamp(lastEnd + 3),
      text: '',
    }]);
  }, [segments]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveStatus('idle');
    try {
      await putSrt(videoId, { language: activeLang, segments });
      setOriginalSegments(segments);
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
    } catch {
      setSaveStatus('error');
    } finally {
      setSaving(false);
    }
  }, [videoId, activeLang, segments]);

  const handleRenderPreview = useCallback(async () => {
    setIsPreviewing(true);
    setPreviewError('');
    try {
      // Save first if dirty
      if (isDirty) {
        await putSrt(videoId, { language: activeLang, segments });
        setOriginalSegments(segments);
        setSaveStatus('saved');
      }
      const blob = await postExportPreview(
        videoId, activeLang, selectedTtsFile,
        videoVol / 100, dubVol / 100,
      );
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setIsPreviewing(false);
    }
  }, [videoId, activeLang, selectedTtsFile, videoVol, dubVol, isDirty, segments, previewUrl]);

  const handleExport = useCallback(async () => {
    setIsExporting(true);
    setExportError('');
    setExportDone(false);
    setExportProgress({ pct: 0, message: 'Starting...' });
    try {
      // Save first if dirty
      if (isDirty) {
        await putSrt(videoId, { language: activeLang, segments });
        setOriginalSegments(segments);
      }
      const { task_id } = await postExport(
        videoId, activeLang, selectedTtsFile,
        videoVol / 100, dubVol / 100,
      );
      subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') {
          setExportProgress({
            pct: Math.round((data.progress as number) * 100),
            message: data.message as string,
          });
        } else if (eventType === 'complete') {
          setIsExporting(false);
          setExportDone(true);
          setExportProgress({ pct: 100, message: 'Export complete' });
          onExportDone?.();
        } else if (eventType === 'error') {
          setIsExporting(false);
          setExportError(data.message as string);
        }
      });
    } catch (e) {
      setIsExporting(false);
      setExportError(e instanceof Error ? e.message : 'Export failed');
    }
  }, [videoId, activeLang, selectedTtsFile, videoVol, dubVol, isDirty, segments, onExportDone]);

  // Cleanup blob on unmount
  useEffect(() => {
    return () => { if (previewUrl) URL.revokeObjectURL(previewUrl); };
  }, [previewUrl]);

  // No-op seek for SegmentList (no video player to sync)
  const noopSeek = useCallback(() => {}, []);

  return (
    <div className="space-y-4">
      {/* Controls Row */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Language */}
        <div className="space-y-0.5">
          <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">Subtitle</label>
          <select
            value={activeLang}
            onChange={e => setActiveLang(e.target.value)}
            className="block bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-0"
          >
            {srtLanguages.map(l => (
              <option key={l} value={l}>
                {l === 'en' ? 'English' : l === 'vi' ? 'Vietnamese' : l === 'zh' ? 'Chinese' : l.toUpperCase()}
              </option>
            ))}
          </select>
        </div>

        {/* TTS File */}
        <div className="space-y-0.5">
          <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">Dub Audio</label>
          <select
            value={selectedTtsFile || ''}
            onChange={e => setSelectedTtsFile(e.target.value || null)}
            className="block bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-0 max-w-[200px]"
          >
            <option value="">No dub</option>
            {ttsList.map(entry => (
              <option key={entry.filename} value={entry.filename}>
                {entry.profile} ({entry.provider} · {entry.language})
              </option>
            ))}
          </select>
        </div>

        {/* Volume Sliders */}
        <div className="space-y-0.5 min-w-[100px]">
          <div className="flex justify-between">
            <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">Video Vol</label>
            <span className="text-[9px] font-mono text-primary">{videoVol}%</span>
          </div>
          <input type="range" min={0} max={200} value={videoVol}
            onChange={e => setVideoVol(Number(e.target.value))}
            className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer" />
        </div>

        <div className="space-y-0.5 min-w-[100px]">
          <div className="flex justify-between">
            <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">Dub Vol</label>
            <span className="text-[9px] font-mono text-primary">{dubVol}%</span>
          </div>
          <input type="range" min={0} max={200} value={dubVol}
            onChange={e => setDubVol(Number(e.target.value))}
            className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
            disabled={!selectedTtsFile} />
        </div>

        <div className="flex-1" />

        {/* Save status */}
        {isDirty && (
          <span className="font-mono text-[9px] text-amber-400 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />Unsaved
          </span>
        )}
        {saveStatus === 'saved' && <span className="font-mono text-[9px] text-emerald-400">Saved</span>}

        <button
          onClick={handleSave}
          disabled={!isDirty || saving}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-bold uppercase tracking-wider transition-all ${
            isDirty ? 'bg-primary text-on-primary-fixed' : 'bg-surface-container-highest text-on-surface-variant'
          } disabled:opacity-50`}
        >
          <span className="material-symbols-outlined text-sm">{saving ? 'progress_activity' : 'save'}</span>
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3">
        <button
          disabled={isPreviewing}
          onClick={handleRenderPreview}
          className="flex-1 py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 bg-surface-container-highest text-on-surface hover:bg-surface-container-high transition-colors disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-sm">{isPreviewing ? 'progress_activity' : 'preview'}</span>
          {isPreviewing ? 'Rendering...' : 'Render Preview (5s)'}
        </button>

        <button
          disabled={isExporting}
          onClick={handleExport}
          className="flex-1 py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 bg-gradient-to-r from-primary to-primary-container text-on-primary-fixed hover:shadow-[0_0_20px_rgba(160,120,255,0.3)] transition-all disabled:opacity-50"
        >
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

      {/* Errors */}
      {(previewError || exportError) && (
        <div className="p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
          {previewError || exportError}
        </div>
      )}

      {/* Preview / Export Video Player */}
      {(previewUrl || exportDone) && (
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">
              {exportDone ? 'Exported Video' : 'Preview'}
            </label>
            {exportDone && (
              <a href={getExportedVideoUrl(videoId)} download
                className="inline-flex items-center gap-1 text-[10px] text-primary hover:underline font-bold">
                <span className="material-symbols-outlined text-xs">download</span>
                Download
              </a>
            )}
          </div>
          <video
            controls
            autoPlay
            className="w-full max-h-[50vh] rounded-lg bg-black"
            src={exportDone ? getExportedVideoUrl(videoId) : previewUrl!}
          />
        </div>
      )}

      {/* Segment List */}
      <div className="border-t border-outline-variant/10 pt-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">Segments</span>
          <span className="font-mono text-[9px] text-zinc-600">{segments.length} segments</span>
        </div>
        <div className="max-h-[300px] overflow-y-auto">
          <SegmentList
            segments={segments}
            currentTime={0}
            onSeek={noopSeek}
            onUpdate={handleUpdateSegment}
            onDelete={handleDeleteSegment}
            onSplit={handleSplitSegment}
            onMerge={handleMergeSegment}
            onAdd={handleAddSegment}
          />
        </div>
      </div>
    </div>
  );
}
