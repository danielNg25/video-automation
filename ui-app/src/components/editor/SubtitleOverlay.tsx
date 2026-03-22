import { useMemo, useCallback, useRef, useState } from 'react';
import type { SubtitleSegment } from '../../api/types';
import { srtTimestampToSeconds } from '../../utils/srtTime';

export interface SubtitleStyle {
  fontName: string;
  fontSize: number;
  outlineWidth: number;
  marginV: number;
  marginH: number;
  bold: boolean;
  shadow: boolean;
  backgroundColor: string;
  backgroundOpacity: number;
}

interface SubtitleOverlayProps {
  segments: SubtitleSegment[];
  currentTime: number;
  style: SubtitleStyle;
  onDragPosition?: (marginH: number, marginV: number) => void;
}

export function SubtitleOverlay({ segments, currentTime, style, onDragPosition }: SubtitleOverlayProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, marginH: 0, marginV: 0 });

  // Find active segment via binary search
  const activeSegment = useMemo(() => {
    if (segments.length === 0) return null;
    let lo = 0;
    let hi = segments.length - 1;
    while (lo <= hi) {
      const mid = Math.floor((lo + hi) / 2);
      const seg = segments[mid];
      const start = srtTimestampToSeconds(seg.startTime);
      const end = srtTimestampToSeconds(seg.endTime);
      if (currentTime >= start && currentTime < end) return seg;
      if (currentTime < start) hi = mid - 1;
      else lo = mid + 1;
    }
    return null;
  }, [segments, currentTime]);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (!onDragPosition) return;
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
      dragStart.current = {
        x: e.clientX,
        y: e.clientY,
        marginH: style.marginH,
        marginV: style.marginV,
      };

      const handleMove = (ev: MouseEvent) => {
        const dx = ev.clientX - dragStart.current.x;
        const dy = -(ev.clientY - dragStart.current.y); // invert: drag up = increase marginV
        onDragPosition(
          dragStart.current.marginH + dx,
          Math.max(0, dragStart.current.marginV + dy),
        );
      };

      const handleUp = () => {
        setIsDragging(false);
        window.removeEventListener('mousemove', handleMove);
        window.removeEventListener('mouseup', handleUp);
      };

      window.addEventListener('mousemove', handleMove);
      window.addEventListener('mouseup', handleUp);
    },
    [onDragPosition, style.marginH, style.marginV],
  );

  if (!activeSegment) return null;

  const scaledFontSize = Math.max(10, style.fontSize * 0.55);
  const scaledOutline = Math.max(0.3, style.outlineWidth * 0.35);

  const textStyle: React.CSSProperties = {
    fontFamily: style.fontName,
    fontSize: `${scaledFontSize}px`,
    fontWeight: style.bold ? 'bold' : 'normal',
    color: 'white',
    textShadow: style.shadow
      ? `0 0 ${scaledOutline}px black, 0 0 ${scaledOutline * 2}px black, 1px 1px 2px rgba(0,0,0,0.8)`
      : `0 0 ${scaledOutline}px black, 0 0 ${scaledOutline * 2}px black`,
    WebkitTextStroke: `${scaledOutline}px black`,
    lineHeight: '1.4',
    cursor: onDragPosition ? (isDragging ? 'grabbing' : 'grab') : 'default',
    userSelect: 'none',
    whiteSpace: 'pre-wrap',
    textAlign: 'center',
    padding: style.backgroundOpacity > 0 ? '2px 6px' : undefined,
    backgroundColor:
      style.backgroundOpacity > 0
        ? `rgba(0,0,0,${style.backgroundOpacity / 100})`
        : undefined,
    borderRadius: style.backgroundOpacity > 0 ? '3px' : undefined,
  };

  return (
    <div
      ref={overlayRef}
      className="absolute left-0 right-0 flex justify-center px-3 text-center pointer-events-none"
      style={{
        bottom: `${Math.max(4, style.marginV * 0.4)}px`,
        transform: `translateX(${style.marginH * 0.3}px)`,
      }}
    >
      <p
        style={textStyle}
        className="pointer-events-auto"
        onMouseDown={handleMouseDown}
      >
        {activeSegment.text}
      </p>
    </div>
  );
}
