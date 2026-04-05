import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { VideoPlayer } from './editor/VideoPlayer';
import { SubtitleOverlay } from './editor/SubtitleOverlay';
import type { SubtitleStyle } from './editor/SubtitleOverlay';
import { SegmentList } from './editor/SegmentList';
import { Timeline } from './editor/Timeline';
import { StylePanel } from './editor/StylePanel';
import { useVideoPlayer } from '../hooks/useVideoPlayer';
import { srtTimestampToSeconds, secondsToSrtTimestamp } from '../utils/srtTime';
import {
  getSrt, putSrt, getProxyVideoUrl, getRawVideoUrl,
  getSubtitleRegion, getVideoStyle, putVideoStyle,
} from '../api/client';
import type { SubtitleSegment } from '../api/types';

interface SubtitleEditorPanelProps {
  videoId: string;
  srtLanguages: string[];
  defaultLang?: string;
}

export function SubtitleEditorPanel({ videoId, srtLanguages, defaultLang }: SubtitleEditorPanelProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playerState, playerControls] = useVideoPlayer(videoRef);

  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [originalSegments, setOriginalSegments] = useState<SubtitleSegment[]>([]);
  const [activeLang, setActiveLang] = useState(defaultLang || srtLanguages[0] || 'zh');
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle');
  const [useProxy, setUseProxy] = useState(true);
  const [videoLoading, setVideoLoading] = useState(true);
  const [rightTab, setRightTab] = useState<'segments' | 'style'>('segments');

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

  const videoSrc = useProxy ? getProxyVideoUrl(videoId) : getRawVideoUrl(videoId);

  const isDirty = useMemo(
    () =>
      JSON.stringify(segments) !== JSON.stringify(originalSegments) ||
      (originalStyle !== null && JSON.stringify(style) !== JSON.stringify(originalStyle)),
    [segments, originalSegments, style, originalStyle],
  );

  // Load style — saved per-video style first, then apply OCR region positioning on top
  useEffect(() => {
    let cancelled = false;

    const loadStyle = async () => {
      // Load saved per-video style as base
      let hasCustomStyle = false;
      try {
        const { style: d, is_custom } = await getVideoStyle(videoId) as { style: Record<string, unknown>; is_custom: boolean };
        if (!cancelled && d && is_custom) {
          hasCustomStyle = true;
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
      } catch { /* no saved style */ }

      // Apply OCR region positioning (always — overrides fontSize/marginV)
      try {
        const region = await getSubtitleRegion(videoId);
        if (!cancelled && region) {
          const scaleY = region.video_height > 0 ? 1920 / region.video_height : 1;
          const regionHeightAss = region.height * scaleY;
          const regionCenterYAss = (region.y + region.height / 2) * scaleY;
          const fontSize = Math.max(16, Math.min(72, Math.round(regionHeightAss * 0.48)));
          const marginV = Math.max(0, Math.round(1920 - regionCenterYAss - fontSize / 2));
          setStyle(prev => ({ ...prev, fontSize, marginV }));
          setOriginalStyle(prev => ({ ...(prev || style), fontSize, marginV }));
        }
      } catch { /* no OCR data — keep defaults */ }
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

  const handleTimelineResize = useCallback((index: number, edge: 'start' | 'end', time: number) => {
    setSegments(prev => prev.map((s, i) => {
      if (i !== index) return s;
      return edge === 'start'
        ? { ...s, startTime: secondsToSrtTimestamp(time) }
        : { ...s, endTime: secondsToSrtTimestamp(time) };
    }));
  }, []);

  const handleDragPosition = useCallback((marginH: number, marginV: number) => {
    setStyle(prev => ({ ...prev, marginH, marginV }));
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveStatus('idle');
    try {
      await putSrt(videoId, { language: activeLang, segments });
      // Save style too
      await putVideoStyle(videoId, {
        font_name: style.fontName, font_size: style.fontSize,
        outline_width: style.outlineWidth, margin_v: style.marginV,
        margin_h: style.marginH, bold: style.bold,
        shadow_depth: style.shadow ? 1 : 0,
        background_color: style.backgroundColor,
        background_opacity: style.backgroundOpacity,
      });
      setOriginalSegments(segments);
      setOriginalStyle(style);
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
    } catch {
      setSaveStatus('error');
    } finally {
      setSaving(false);
    }
  }, [videoId, activeLang, segments, style]);

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={activeLang}
          onChange={e => setActiveLang(e.target.value)}
          className="bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-0"
        >
          {srtLanguages.map(l => (
            <option key={l} value={l}>
              {l === 'en' ? 'English' : l === 'vi' ? 'Vietnamese' : l === 'zh' ? 'Chinese' : l.toUpperCase()}
            </option>
          ))}
        </select>
        <select
          value={useProxy ? '360p' : 'full'}
          onChange={e => { setUseProxy(e.target.value === '360p'); setVideoLoading(true); }}
          className="bg-surface-container-highest border-none text-[10px] text-on-surface py-1.5 px-2 rounded focus:ring-0 font-mono"
        >
          <option value="360p">360p</option>
          <option value="full">Full Res</option>
        </select>

        <div className="flex-1" />

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
            isDirty ? 'bg-primary text-on-primary-fixed hover:shadow-lg' : 'bg-surface-container-highest text-on-surface-variant'
          } disabled:opacity-50`}
        >
          <span className="material-symbols-outlined text-sm">{saving ? 'progress_activity' : 'save'}</span>
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>

      {/* Video + Overlay */}
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

      {/* Timeline */}
      <Timeline
        segments={segments}
        currentTime={playerState.currentTime}
        duration={playerState.duration}
        onSeek={playerControls.seek}
        onResizeSegment={handleTimelineResize}
      />

      {/* Tabs: Segments / Style */}
      <div className="border-t border-outline-variant/10 pt-3">
        <div className="flex items-center gap-1 mb-3">
          {(['segments', 'style'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setRightTab(tab)}
              className={`px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider rounded ${
                rightTab === tab ? 'bg-primary/20 text-primary' : 'text-zinc-500 hover:text-on-surface'
              }`}
            >
              {tab}
            </button>
          ))}
          <span className="ml-auto font-mono text-[9px] text-zinc-600">{segments.length} segments</span>
        </div>

        {rightTab === 'segments' ? (
          <div className="max-h-[300px] overflow-y-auto">
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
        ) : (
          <StylePanel style={style} onChange={setStyle} />
        )}
      </div>
    </div>
  );
}
