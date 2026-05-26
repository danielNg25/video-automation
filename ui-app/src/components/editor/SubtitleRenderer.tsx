import { useMemo, useCallback, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import type { SubtitleSegment } from '../../api/types';
import type { SubtitleStyleSpec } from '../../api/types';
import { srtTimestampToSeconds } from '../../utils/srtTime';

interface Props {
  segments: SubtitleSegment[];
  currentTime: number;
  spec: SubtitleStyleSpec;
  onDragPosition?: (marginH_pct: number, marginV_pct: number) => void;
  videoRect?: { offsetX: number; offsetY: number; width: number; height: number };
}

/** Pure-function spec → text-element CSS. Exported for testing. */
export function specToCss(spec: SubtitleStyleSpec, videoW: number, videoH: number): CSSProperties {
  const px = {
    fontSize:  spec.text.font_size       * videoH / 100,
    marginV:   spec.position.margin_v    * videoH / 100,
    marginH:   spec.position.margin_h    * videoW / 100,
    outline:   spec.outline.width        * videoH / 100,
    radius:    spec.background.radius    * videoH / 100,
    padX:      spec.background.padding_x * videoW / 100,
    padY:      spec.background.padding_y * videoH / 100,
  };

  const hexToRgb = (hex: string): [number, number, number] => {
    if (!hex.startsWith('#') || hex.length !== 7) return [0, 0, 0];
    return [
      parseInt(hex.slice(1, 3), 16),
      parseInt(hex.slice(3, 5), 16),
      parseInt(hex.slice(5, 7), 16),
    ];
  };

  const [tr, tg, tb] = hexToRgb(spec.text.color);
  const [or, og, ob] = hexToRgb(spec.outline.color);
  const [br, bg_, bb] = hexToRgb(spec.background.color);
  const bgAlpha = spec.background.opacity / 100;

  const showBg = spec.background.shape !== 'none' && spec.background.opacity > 0;
  const css: CSSProperties = {
    fontFamily: spec.text.font_name,
    fontSize: px.fontSize,
    fontWeight: spec.text.bold ? 'bold' : 'normal',
    color: `rgb(${tr},${tg},${tb})`,
    WebkitTextStroke: `${px.outline}px rgb(${or},${og},${ob})`,
    textShadow: spec.shadow.depth > 0
      ? `0 0 ${spec.shadow.depth * videoH / 100}px rgb(${or},${og},${ob})`
      : undefined,
    backgroundColor: showBg ? `rgba(${br},${bg_},${bb},${bgAlpha})` : undefined,
    borderRadius: showBg && spec.background.shape === 'rounded' ? `${px.radius}px` : undefined,
    padding: showBg ? `${px.padY}px ${px.padX}px` : undefined,
    lineHeight: '1.4',
    textAlign: 'center',
    whiteSpace: 'pre-wrap',
    userSelect: 'none',
  };

  // Anchor by alignment
  const isBottom = spec.position.alignment.startsWith('bottom');
  const isTop = spec.position.alignment.startsWith('top');
  if (isBottom) css.bottom = px.marginV;
  else if (isTop) css.top = px.marginV;
  else css.top = videoH / 2;

  return css;
}

export function SubtitleRenderer({ segments, currentTime, spec, onDragPosition, videoRect }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, marginH_pct: 0, marginV_pct: 0 });

  const activeSegment = useMemo(() => {
    if (segments.length === 0) return null;
    let lo = 0, hi = segments.length - 1;
    while (lo <= hi) {
      const mid = Math.floor((lo + hi) / 2);
      const s = segments[mid];
      const start = srtTimestampToSeconds(s.startTime);
      const end = srtTimestampToSeconds(s.endTime);
      if (currentTime >= start && currentTime < end) return s;
      if (currentTime < start) hi = mid - 1; else lo = mid + 1;
    }
    return null;
  }, [segments, currentTime]);

  const videoW = videoRect?.width ?? 0;
  const videoH = videoRect?.height ?? 0;
  const css = useMemo(
    () => (videoW > 0 && videoH > 0 ? specToCss(spec, videoW, videoH) : {}),
    [spec, videoW, videoH],
  );

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (!onDragPosition || videoH === 0) return;
    e.preventDefault(); e.stopPropagation();
    setIsDragging(true);
    dragStart.current = {
      x: e.clientX, y: e.clientY,
      marginH_pct: spec.position.margin_h,
      marginV_pct: spec.position.margin_v,
    };
    const handleMove = (ev: MouseEvent) => {
      const dxPx = ev.clientX - dragStart.current.x;
      const dyPx = -(ev.clientY - dragStart.current.y); // up = increase margin_v
      onDragPosition(
        dragStart.current.marginH_pct + (dxPx * 100 / videoW),
        Math.max(0, dragStart.current.marginV_pct + (dyPx * 100 / videoH)),
      );
    };
    const handleUp = () => {
      setIsDragging(false);
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
  }, [onDragPosition, spec.position.margin_h, spec.position.margin_v, videoW, videoH]);

  const overlayStyle: CSSProperties = videoRect
    ? { position: 'absolute', top: videoRect.offsetY, left: videoRect.offsetX,
        width: videoRect.width, height: videoRect.height, pointerEvents: 'none' }
    : { position: 'absolute', inset: 0, pointerEvents: 'none' };

  return (
    <div ref={overlayRef} style={overlayStyle}>
      {activeSegment && (
        <div
          style={{
            position: 'absolute',
            left: '50%',
            transform: `translateX(-50%) translateX(${spec.position.margin_h * videoW / 100}px)`,
            cursor: isDragging ? 'grabbing' : (onDragPosition ? 'grab' : 'default'),
            ...css,
          }}
          className="pointer-events-auto"
          onMouseDown={handleMouseDown}
        >
          {activeSegment.text}
        </div>
      )}
    </div>
  );
}
