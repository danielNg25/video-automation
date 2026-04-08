import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { VideoPlayer } from './editor/VideoPlayer';
import { SubtitleOverlay } from './editor/SubtitleOverlay';
import type { SubtitleStyle } from './editor/SubtitleOverlay';
import { SegmentList } from './editor/SegmentList';
import { Timeline } from './editor/Timeline';
import { StylePanel } from './editor/StylePanel';
import type { BlurConfig } from './editor/StylePanel';
import { useVideoPlayer } from '../hooks/useVideoPlayer';
import { srtTimestampToSeconds, secondsToSrtTimestamp } from '../utils/srtTime';
import {
  getSrt, putSrt, getProxyVideoUrl, getRawVideoUrl,
  getSubtitleRegion, getVideoStyle, putVideoStyle,
  postExportPreview, postExport, getExportedVideoUrl,
  getExportStatus, deleteExport,
  subscribeSSE, getTTSAudioUrl,
} from '../api/client';
import type { TTSAudioEntry } from '../api/client';
import type { SubtitleSegment } from '../api/types';

interface SubtitleEditorPanelProps {
  videoId: string;
  srtLanguages: string[];
  defaultLang?: string;
  ttsList: TTSAudioEntry[];
  onExportDone?: () => void;
  onReload?: () => void;
}

export function SubtitleEditorPanel({ videoId, srtLanguages, defaultLang, ttsList, onExportDone, onReload }: SubtitleEditorPanelProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playerState, playerControls] = useVideoPlayer(videoRef);

  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [originalSegments, setOriginalSegments] = useState<SubtitleSegment[]>([]);
  const [activeLang, setActiveLang] = useState(defaultLang || srtLanguages.find(l => l !== 'zh') || srtLanguages[0] || 'vi');
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');
  const [useProxy, setUseProxy] = useState(true);
  const [videoLoading, setVideoLoading] = useState(true);
  const [bottomTab, setBottomTab] = useState<'segments' | 'style' | 'export'>('export');

  // Style
  const [style, setStyle] = useState<SubtitleStyle>({
    fontName: 'Arial', fontSize: 24, outlineWidth: 2,
    marginV: 30, marginH: 0, bold: true, shadow: true,
    backgroundColor: '', backgroundOpacity: 90,
  });
  const [originalStyle, setOriginalStyle] = useState<SubtitleStyle | null>(null);

  // Blur config
  const [blurConfig, setBlurConfig] = useState<BlurConfig>({ enabled: true, mode: 'blur', strength: 15 });
  const [originalBlurConfig, setOriginalBlurConfig] = useState<BlurConfig>({ enabled: true, mode: 'blur', strength: 15 });

  // OCR region for CSS blur approximation in live editor
  const [ocrRegion, setOcrRegion] = useState<{ x: number; y: number; width: number; height: number; videoWidth: number; videoHeight: number } | null>(null);

  // Track actual video element rect within its container for accurate blur positioning
  const [videoRect, setVideoRect] = useState<{ offsetX: number; offsetY: number; width: number; height: number } | null>(null);
  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    const update = () => {
      const parent = el.parentElement;
      if (!parent) return;
      const pr = parent.getBoundingClientRect();
      const vr = el.getBoundingClientRect();
      setVideoRect({
        offsetX: vr.left - pr.left,
        offsetY: vr.top - pr.top,
        width: vr.width,
        height: vr.height,
      });
    };
    const ro = new ResizeObserver(update);
    ro.observe(el);
    el.addEventListener('loadeddata', update);
    update();
    return () => { ro.disconnect(); el.removeEventListener('loadeddata', update); };
  }, []);

  // Export controls
  const [selectedTtsFile, setSelectedTtsFile] = useState<string | null>(null);
  const [videoVol, setVideoVol] = useState(30);
  const [dubVol, setDubVol] = useState(100);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [isExporting, setIsExporting] = useState(false);
  const [exportProgress, setExportProgress] = useState({ pct: 0, message: '' });
  const [exportError, setExportError] = useState('');
  const [exportDone, setExportDone] = useState(false);

  const ttsAudioRef = useRef<HTMLAudioElement>(null);

  const videoSrc = useProxy ? getProxyVideoUrl(videoId) : getRawVideoUrl(videoId);

  // Derive TTS audio URL from selected file
  const ttsAudioSrc = useMemo(() => {
    if (!selectedTtsFile) return null;
    const entry = ttsList.find(e => e.filename === selectedTtsFile);
    if (!entry) return null;
    return getTTSAudioUrl(videoId, entry.language, entry.filename);
  }, [videoId, selectedTtsFile, ttsList]);

  // Sync TTS audio playback with video player
  useEffect(() => {
    const audio = ttsAudioRef.current;
    const video = videoRef.current;
    if (!audio || !video || !ttsAudioSrc) return;

    audio.volume = dubVol / 100;

    const syncPlay = () => { audio.currentTime = video.currentTime; audio.play().catch(() => {}); };
    const syncPause = () => audio.pause();
    const syncSeek = () => { audio.currentTime = video.currentTime; };

    video.addEventListener('play', syncPlay);
    video.addEventListener('pause', syncPause);
    video.addEventListener('seeked', syncSeek);

    // If video is already playing, start audio
    if (!video.paused) syncPlay();

    return () => {
      video.removeEventListener('play', syncPlay);
      video.removeEventListener('pause', syncPause);
      video.removeEventListener('seeked', syncSeek);
      audio.pause();
    };
  }, [ttsAudioSrc, dubVol]);

  // Update audio volume in real-time
  useEffect(() => {
    if (ttsAudioRef.current) ttsAudioRef.current.volume = Math.min(1, dubVol / 100);
  }, [dubVol]);

  // Update video volume
  useEffect(() => {
    if (videoRef.current) videoRef.current.volume = Math.min(1, videoVol / 100);
  }, [videoVol]);

  const isDirty = useMemo(
    () =>
      JSON.stringify(segments) !== JSON.stringify(originalSegments) ||
      (originalStyle !== null && JSON.stringify(style) !== JSON.stringify(originalStyle)) ||
      JSON.stringify(blurConfig) !== JSON.stringify(originalBlurConfig),
    [segments, originalSegments, style, originalStyle, blurConfig, originalBlurConfig],
  );

  // Auto-select first TTS file
  useEffect(() => {
    if (ttsList.length > 0 && !selectedTtsFile) {
      setSelectedTtsFile(ttsList[0].filename);
    }
  }, [ttsList, selectedTtsFile]);

  // Load style: saved per-video first, then OCR region positioning on top
  useEffect(() => {
    let cancelled = false;
    const loadStyle = async () => {
      try {
        const { style: d, is_custom } = await getVideoStyle(videoId) as { style: Record<string, unknown>; is_custom: boolean };
        if (!cancelled && d && is_custom) {
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
          // Load blur config from saved style
          if (d.blur_enabled !== undefined) {
            const loadedBlur: BlurConfig = {
              enabled: Boolean(d.blur_enabled),
              mode: (d.blur_mode as BlurConfig['mode']) || 'blur',
              strength: (d.blur_strength as number) || 15,
            };
            setBlurConfig(loadedBlur);
            setOriginalBlurConfig(loadedBlur);
          }
        }
      } catch { /* no saved style */ }
      try {
        const region = await getSubtitleRegion(videoId);
        if (!cancelled && region) {
          setOcrRegion({
            x: region.x, y: region.y, width: region.width, height: region.height,
            videoWidth: region.video_width, videoHeight: region.video_height,
          });
          const scaleY = region.video_height > 0 ? 1920 / region.video_height : 1;
          const regionHeightAss = region.height * scaleY;
          const regionCenterYAss = (region.y + region.height / 2) * scaleY;
          const fontSize = Math.max(16, Math.min(72, Math.round(regionHeightAss * 0.48)));
          const marginV = Math.max(0, Math.round(1920 - regionCenterYAss - fontSize / 2));
          setStyle(prev => ({ ...prev, fontSize, marginV }));
          setOriginalStyle(prev => ({ ...(prev || style), fontSize, marginV }));
        }
      } catch { /* no OCR data */ }
    };
    loadStyle();
    return () => { cancelled = true; };
  }, [videoId]);

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
      const next = [...prev];
      next.splice(index, 1,
        { ...seg, id: seg.id, endTime: secondsToSrtTimestamp(splitTime), text: words.slice(0, splitIdx).join(' ') },
        { ...seg, id: seg.id + 0.5, startTime: secondsToSrtTimestamp(splitTime), text: words.slice(splitIdx).join(' ') || '...' },
      );
      return next.map((s, i) => ({ ...s, id: i + 1 }));
    });
  }, []);
  const handleMergeSegment = useCallback((index: number) => {
    setSegments(prev => {
      if (index >= prev.length - 1) return prev;
      const a = prev[index], b = prev[index + 1];
      const next = [...prev];
      next.splice(index, 2, { ...a, endTime: b.endTime, text: `${a.text} ${b.text}` });
      return next.map((s, i) => ({ ...s, id: i + 1 }));
    });
  }, []);
  const handleAddSegment = useCallback(() => {
    const lastEnd = segments.length > 0 ? srtTimestampToSeconds(segments[segments.length - 1].endTime) : 0;
    setSegments(prev => [...prev, { id: prev.length + 1, startTime: secondsToSrtTimestamp(lastEnd + 0.5), endTime: secondsToSrtTimestamp(lastEnd + 3), text: '' }]);
  }, [segments]);
  const handleTimelineResize = useCallback((index: number, edge: 'start' | 'end', time: number) => {
    setSegments(prev => prev.map((s, i) => {
      if (i !== index) return s;
      return edge === 'start' ? { ...s, startTime: secondsToSrtTimestamp(time) } : { ...s, endTime: secondsToSrtTimestamp(time) };
    }));
  }, []);
  const handleDragPosition = useCallback((marginH: number, marginV: number) => {
    setStyle(prev => ({ ...prev, marginH, marginV }));
  }, []);

  // Reload data from server
  const handleReload = useCallback(async () => {
    getSrt(videoId, activeLang)
      .then(res => { setSegments(res.segments); setOriginalSegments(res.segments); setSaveStatus('idle'); })
      .catch(() => {});
    // Reload style
    getVideoStyle(videoId)
      .then(({ style: d, is_custom }) => {
        if (d && is_custom) {
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
          if (d.blur_enabled !== undefined) {
            const loadedBlur: BlurConfig = {
              enabled: Boolean(d.blur_enabled),
              mode: (d.blur_mode as BlurConfig['mode']) || 'blur',
              strength: (d.blur_strength as number) || 15,
            };
            setBlurConfig(loadedBlur);
            setOriginalBlurConfig(loadedBlur);
          }
        }
      })
      .catch(() => {});
    onReload?.();
  }, [videoId, activeLang, onReload]);

  // Save SRT + style
  const handleSave = useCallback(async () => {
    setSaving(true); setSaveStatus('idle');
    try {
      await putSrt(videoId, { language: activeLang, segments });
      await putVideoStyle(videoId, {
        font_name: style.fontName, font_size: style.fontSize, outline_width: style.outlineWidth,
        margin_v: style.marginV, margin_h: style.marginH, bold: style.bold,
        shadow_depth: style.shadow ? 1 : 0, background_color: style.backgroundColor, background_opacity: style.backgroundOpacity,
        blur_enabled: blurConfig.enabled, blur_mode: blurConfig.mode, blur_strength: blurConfig.strength,
      });
      setOriginalSegments(segments); setOriginalStyle(style); setOriginalBlurConfig(blurConfig);
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
    } catch { setSaveStatus('error'); }
    finally { setSaving(false); }
  }, [videoId, activeLang, segments, style]);

  // Render ffmpeg preview (auto-saves first)
  const handleRenderPreview = useCallback(async () => {
    setIsPreviewing(true); setPreviewError('');
    try {
      if (isDirty) { await handleSave(); }
      const blob = await postExportPreview(videoId, activeLang, selectedTtsFile, videoVol / 100, dubVol / 100);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (e) { setPreviewError(e instanceof Error ? e.message : 'Preview failed'); }
    finally { setIsPreviewing(false); }
  }, [videoId, activeLang, selectedTtsFile, videoVol, dubVol, isDirty, handleSave, previewUrl]);

  // Cache-bust timestamp for exported video URL
  const [exportTimestamp, setExportTimestamp] = useState(0);

  // Check if export already exists — only on first mount
  const exportChecked = useRef(false);
  useEffect(() => {
    if (exportChecked.current) return;
    exportChecked.current = true;
    getExportStatus(videoId).then(status => {
      if (status.exists) {
        setExportDone(true);
        setExportTimestamp(status.modified ? Math.round(status.modified * 1000) : Date.now());
      }
    }).catch(() => {});
  }, [videoId]);

  // Export full video (auto-saves first, deletes old export)
  const handleExport = useCallback(async () => {
    setIsExporting(true); setExportError(''); setExportDone(false);
    setExportProgress({ pct: 0, message: 'Starting...' });
    try {
      // Delete old export first
      await deleteExport(videoId).catch(() => {});
      if (isDirty) { await handleSave(); }
      const { task_id } = await postExport(videoId, activeLang, selectedTtsFile, videoVol / 100, dubVol / 100);
      subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') setExportProgress({ pct: Math.round((data.progress as number) * 100), message: data.message as string });
        else if (eventType === 'complete') { setIsExporting(false); setExportDone(true); setExportTimestamp(Date.now()); setExportProgress({ pct: 100, message: 'Export complete' }); onExportDone?.(); }
        else if (eventType === 'error') { setIsExporting(false); setExportError(data.message as string); }
      });
    } catch (e) { setIsExporting(false); setExportError(e instanceof Error ? e.message : 'Export failed'); }
  }, [videoId, activeLang, selectedTtsFile, videoVol, dubVol, isDirty, handleSave, onExportDone]);

  useEffect(() => { return () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }; }, [previewUrl]);

  return (
    <div className="space-y-3">
      {/* Top toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <select value={activeLang} onChange={e => setActiveLang(e.target.value)}
          className="bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-0">
          {srtLanguages.map(l => <option key={l} value={l}>{l === 'en' ? 'English' : l === 'vi' ? 'Vietnamese' : l === 'zh' ? 'Chinese' : l.toUpperCase()}</option>)}
        </select>
        <select value={useProxy ? '360p' : 'full'} onChange={e => { setUseProxy(e.target.value === '360p'); setVideoLoading(true); }}
          className="bg-surface-container-highest border-none text-[10px] text-on-surface py-1.5 px-2 rounded focus:ring-0 font-mono">
          <option value="360p">360p</option>
          <option value="full">Full Res</option>
        </select>
        {ttsList.length > 0 && (
          <>
            <div className="w-px h-5 bg-zinc-700 mx-1" />
            <select value={selectedTtsFile || ''} onChange={e => setSelectedTtsFile(e.target.value || null)}
              className="bg-surface-container-highest border-none text-[10px] text-on-surface py-1.5 px-2 rounded focus:ring-0 max-w-[180px]">
              <option value="">No dub</option>
              {ttsList.map(entry => <option key={entry.filename} value={entry.filename}>{entry.profile} ({entry.language})</option>)}
            </select>
          </>
        )}
        <div className="flex-1" />
        {isDirty && <span className="font-mono text-[9px] text-amber-400 flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber-400" />Unsaved</span>}
        {saveStatus === 'saved' && <span className="font-mono text-[9px] text-emerald-400">Saved</span>}
        <button onClick={handleReload} title="Reload data"
          className="flex items-center gap-1 px-2 py-1.5 rounded text-xs text-zinc-400 hover:text-on-surface hover:bg-surface-container-highest transition-colors">
          <span className="material-symbols-outlined text-sm">refresh</span>
        </button>
        <button onClick={handleSave} disabled={!isDirty || saving}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-bold uppercase tracking-wider transition-all ${isDirty ? 'bg-primary text-on-primary-fixed' : 'bg-surface-container-highest text-on-surface-variant'} disabled:opacity-50`}>
          <span className="material-symbols-outlined text-sm">{saving ? 'progress_activity' : 'save'}</span>
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>

      {/* Main: Video (left) + Tabs (right) */}
      <div className="flex gap-4">
        {/* Left: Video + Timeline */}
        <div className="w-[65%] shrink-0 space-y-3">
          <VideoPlayer ref={videoRef} src={videoSrc} state={playerState} controls={playerControls} loading={videoLoading} onLoadingChange={setVideoLoading}>
            {blurConfig.enabled && ocrRegion && ocrRegion.videoHeight > 0 && videoRect && videoRect.width > 0 && (() => {
              const pos: React.CSSProperties = {
                position: 'absolute',
                left: `${videoRect.offsetX + (ocrRegion.x / ocrRegion.videoWidth) * videoRect.width}px`,
                top: `${videoRect.offsetY + (ocrRegion.y / ocrRegion.videoHeight) * videoRect.height}px`,
                width: `${(ocrRegion.width / ocrRegion.videoWidth) * videoRect.width}px`,
                height: `${(ocrRegion.height / ocrRegion.videoHeight) * videoRect.height}px`,
                pointerEvents: 'none',
              };
              const blurPx = blurConfig.strength * 0.5;
              if (blurConfig.mode === 'fill') {
                return <div style={{ ...pos, backgroundColor: 'rgba(0,0,0,0.95)' }} />;
              }
              if (blurConfig.mode === 'pixelate') {
                // CSS can't do true mosaic — approximate with heavy blur + saturate
                return <div style={{ ...pos, backdropFilter: `blur(${blurPx * 3}px) saturate(0.5)`, WebkitBackdropFilter: `blur(${blurPx * 3}px) saturate(0.5)`, backgroundColor: 'rgba(0,0,0,0.1)' }} />;
              }
              return <div style={{ ...pos, backdropFilter: `blur(${blurPx}px)`, WebkitBackdropFilter: `blur(${blurPx}px)`, backgroundColor: 'rgba(0,0,0,0.15)' }} />;
            })()}
            <SubtitleOverlay segments={segments} currentTime={playerState.currentTime} style={style} onDragPosition={handleDragPosition} videoRect={videoRect || undefined} />
          </VideoPlayer>
          {ttsAudioSrc && <audio ref={ttsAudioRef} src={ttsAudioSrc} preload="auto" style={{ display: 'none' }} />}
          <Timeline segments={segments} currentTime={playerState.currentTime} duration={playerState.duration} onSeek={playerControls.seek} onResizeSegment={handleTimelineResize} />
        </div>

        {/* Right: Tabs */}
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="flex items-center gap-1 mb-2">
            {(['segments', 'style', 'export'] as const).map(tab => (
              <button key={tab} onClick={() => setBottomTab(tab)}
                className={`px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider rounded ${bottomTab === tab ? 'bg-primary/20 text-primary' : 'text-zinc-500 hover:text-on-surface'}`}>
                {tab}
              </button>
            ))}
            <span className="ml-auto font-mono text-[9px] text-zinc-600">{segments.length} seg</span>
          </div>

          <div className="flex-1 overflow-y-auto">
            {/* Segments Tab */}
            {bottomTab === 'segments' && (
              <SegmentList segments={segments} currentTime={playerState.currentTime} onSeek={playerControls.seek}
                onUpdate={handleUpdateSegment} onDelete={handleDeleteSegment} onSplit={handleSplitSegment}
                onMerge={handleMergeSegment} onAdd={handleAddSegment} />
            )}

            {/* Style Tab */}
            {bottomTab === 'style' && (
              <StylePanel style={style} onChange={setStyle}
                blur={blurConfig} onBlurChange={setBlurConfig} hasOcrRegion={!!ocrRegion} />
            )}

            {/* Export Tab */}
            {bottomTab === 'export' && (
              <div className="space-y-3">
                <div className="space-y-2">
                  <div className="space-y-1">
                    <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">Dub Audio</label>
                    <select value={selectedTtsFile || ''} onChange={e => setSelectedTtsFile(e.target.value || null)}
                      className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-0">
                      <option value="">No dub</option>
                      {ttsList.map(entry => <option key={entry.filename} value={entry.filename}>{entry.profile} ({entry.provider} · {entry.language})</option>)}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <div className="flex justify-between">
                      <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">Video Volume</label>
                      <span className="text-[9px] font-mono text-primary">{videoVol}%</span>
                    </div>
                    <input type="range" min={0} max={200} value={videoVol} onChange={e => setVideoVol(Number(e.target.value))}
                      className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer" />
                  </div>
                  <div className="space-y-1">
                    <div className="flex justify-between">
                      <label className="text-[9px] text-zinc-500 uppercase tracking-tighter font-bold">Dub Volume</label>
                      <span className="text-[9px] font-mono text-primary">{dubVol}%</span>
                    </div>
                    <input type="range" min={0} max={200} value={dubVol} onChange={e => setDubVol(Number(e.target.value))}
                      className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer" disabled={!selectedTtsFile} />
                  </div>
                </div>

                <div className="flex gap-2">
                  <button disabled={isPreviewing} onClick={handleRenderPreview}
                    className="flex-1 py-2 rounded-md font-bold text-[10px] uppercase tracking-wider flex items-center justify-center gap-1.5 bg-surface-container-highest text-on-surface hover:bg-surface-container-high transition-colors disabled:opacity-50">
                    <span className="material-symbols-outlined text-sm">{isPreviewing ? 'progress_activity' : 'preview'}</span>
                    {isPreviewing ? 'Rendering...' : 'Preview 5s'}
                  </button>
                  <button disabled={isExporting} onClick={handleExport}
                    className="flex-1 py-2 rounded-md font-bold text-[10px] uppercase tracking-wider flex items-center justify-center gap-1.5 bg-gradient-to-r from-primary to-primary-container text-on-primary-fixed hover:shadow-[0_0_20px_rgba(160,120,255,0.3)] transition-all disabled:opacity-50">
                    <span className="material-symbols-outlined text-sm">{isExporting ? 'progress_activity' : 'movie_edit'}</span>
                    {isExporting ? 'Exporting...' : exportDone ? 'Re-Export' : 'Export'}
                  </button>
                </div>

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

                {(previewError || exportError) && (
                  <div className="p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">{previewError || exportError}</div>
                )}

                {(previewUrl || exportDone) && (
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">{exportDone ? 'Exported' : 'Preview'}</label>
                      {exportDone && (
                        <a href={`${getExportedVideoUrl(videoId)}?t=${exportTimestamp}`} download className="inline-flex items-center gap-1 text-[10px] text-primary hover:underline font-bold">
                          <span className="material-symbols-outlined text-xs">download</span>
                        </a>
                      )}
                    </div>
                    <video controls autoPlay className="w-full rounded-lg bg-black"
                      src={exportDone ? `${getExportedVideoUrl(videoId)}?t=${exportTimestamp}` : previewUrl!} />
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
