import { useRef, useCallback, useState, useMemo } from 'react';
import type { SubtitleSegment } from '../../api/types';
import { srtTimestampToSeconds, secondsToSrtTimestamp, formatDisplayTime } from '../../utils/srtTime';

interface TimelineProps {
  segments: SubtitleSegment[];
  currentTime: number;
  duration: number;
  onSeek: (time: number) => void;
  onResizeSegment: (index: number, field: 'startTime' | 'endTime', newTime: number) => void;
}

const TIMELINE_HEIGHT = 64;
const SEGMENT_Y = 16;
const SEGMENT_H = 28;
const TICK_HEIGHT = 8;

export function Timeline({ segments, currentTime, duration, onSeek, onResizeSegment }: TimelineProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dragging, setDragging] = useState<{ index: number; field: 'startTime' | 'endTime' } | null>(null);
  const [hoverTime, setHoverTime] = useState<number | null>(null);

  const effectiveDuration = duration || 60;

  // Convert x position to time
  const xToTime = useCallback(
    (clientX: number) => {
      const svg = svgRef.current;
      if (!svg) return 0;
      const rect = svg.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      return ratio * effectiveDuration;
    },
    [effectiveDuration],
  );

  // Generate time tick marks
  const ticks = useMemo(() => {
    const step = effectiveDuration <= 30 ? 5 : effectiveDuration <= 120 ? 10 : 30;
    const result: number[] = [];
    for (let t = 0; t <= effectiveDuration; t += step) result.push(t);
    return result;
  }, [effectiveDuration]);

  const handleSvgClick = useCallback(
    (e: React.MouseEvent) => {
      if (dragging) return;
      onSeek(xToTime(e.clientX));
    },
    [xToTime, onSeek, dragging],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      setHoverTime(xToTime(e.clientX));
    },
    [xToTime],
  );

  const handleEdgeDown = useCallback(
    (e: React.MouseEvent, index: number, field: 'startTime' | 'endTime') => {
      e.stopPropagation();
      setDragging({ index, field });

      const handleMove = (ev: MouseEvent) => {
        const time = xToTime(ev.clientX);
        const seg = segments[index];
        const start = srtTimestampToSeconds(seg.startTime);
        const end = srtTimestampToSeconds(seg.endTime);

        if (field === 'startTime') {
          // Clamp: 0 ≤ start < end - 0.1
          const clamped = Math.max(0, Math.min(time, end - 0.1));
          onResizeSegment(index, field, clamped);
        } else {
          // Clamp: start + 0.1 ≤ end ≤ duration
          const clamped = Math.max(start + 0.1, Math.min(time, effectiveDuration));
          onResizeSegment(index, field, clamped);
        }
      };

      const handleUp = () => {
        setDragging(null);
        window.removeEventListener('mousemove', handleMove);
        window.removeEventListener('mouseup', handleUp);
      };

      window.addEventListener('mousemove', handleMove);
      window.addEventListener('mouseup', handleUp);
    },
    [segments, xToTime, onResizeSegment, effectiveDuration],
  );

  const timeToPercent = (t: number) => `${(t / effectiveDuration) * 100}%`;

  return (
    <div className="bg-zinc-900/80 rounded-lg border border-outline-variant/10 px-2 py-1">
      <svg
        ref={svgRef}
        width="100%"
        height={TIMELINE_HEIGHT}
        className="cursor-crosshair select-none"
        onClick={handleSvgClick}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverTime(null)}
      >
        {/* Time ticks */}
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={timeToPercent(t)}
              y1={TIMELINE_HEIGHT - TICK_HEIGHT}
              x2={timeToPercent(t)}
              y2={TIMELINE_HEIGHT}
              stroke="#525252"
              strokeWidth={0.5}
            />
            <text
              x={timeToPercent(t)}
              y={TIMELINE_HEIGHT - TICK_HEIGHT - 2}
              fill="#71717a"
              fontSize={8}
              textAnchor="middle"
              fontFamily="monospace"
            >
              {formatDisplayTime(t)}
            </text>
          </g>
        ))}

        {/* Segments */}
        {segments.map((seg, i) => {
          const start = srtTimestampToSeconds(seg.startTime);
          const end = srtTimestampToSeconds(seg.endTime);
          const x1 = (start / effectiveDuration) * 100;
          const w = ((end - start) / effectiveDuration) * 100;
          const isActive =
            currentTime >= start && currentTime < end;

          return (
            <g key={seg.id}>
              {/* Segment bar */}
              <rect
                x={`${x1}%`}
                y={SEGMENT_Y}
                width={`${w}%`}
                height={SEGMENT_H}
                rx={3}
                fill={isActive ? 'rgba(208,188,255,0.4)' : 'rgba(208,188,255,0.15)'}
                stroke={isActive ? 'rgba(208,188,255,0.7)' : 'rgba(208,188,255,0.25)'}
                strokeWidth={1}
              />

              {/* Left drag handle */}
              <rect
                x={`${x1}%`}
                y={SEGMENT_Y}
                width={6}
                height={SEGMENT_H}
                fill="transparent"
                className="cursor-col-resize"
                onMouseDown={(e) => handleEdgeDown(e, i, 'startTime')}
              />
              {/* Right drag handle */}
              <rect
                x={`${x1 + w - 0.5}%`}
                y={SEGMENT_Y}
                width={6}
                height={SEGMENT_H}
                fill="transparent"
                className="cursor-col-resize"
                style={{ transform: 'translateX(-5px)' }}
                onMouseDown={(e) => handleEdgeDown(e, i, 'endTime')}
              />

              {/* Segment index label */}
              {w > 2 && (
                <text
                  x={`${x1 + w / 2}%`}
                  y={SEGMENT_Y + SEGMENT_H / 2 + 3}
                  fill="rgba(255,255,255,0.5)"
                  fontSize={8}
                  textAnchor="middle"
                  fontFamily="monospace"
                  className="pointer-events-none"
                >
                  {i + 1}
                </text>
              )}
            </g>
          );
        })}

        {/* Playhead */}
        <line
          x1={timeToPercent(currentTime)}
          y1={0}
          x2={timeToPercent(currentTime)}
          y2={TIMELINE_HEIGHT}
          stroke="#ef4444"
          strokeWidth={1.5}
        />
        <circle
          cx={timeToPercent(currentTime)}
          cy={4}
          r={4}
          fill="#ef4444"
        />

        {/* Hover indicator */}
        {hoverTime !== null && !dragging && (
          <>
            <line
              x1={timeToPercent(hoverTime)}
              y1={0}
              x2={timeToPercent(hoverTime)}
              y2={TIMELINE_HEIGHT}
              stroke="rgba(255,255,255,0.15)"
              strokeWidth={0.5}
              strokeDasharray="2,2"
              className="pointer-events-none"
            />
            <text
              x={timeToPercent(hoverTime)}
              y={10}
              fill="rgba(255,255,255,0.4)"
              fontSize={8}
              textAnchor="middle"
              fontFamily="monospace"
              className="pointer-events-none"
            >
              {formatDisplayTime(hoverTime)}
            </text>
          </>
        )}
      </svg>
    </div>
  );
}
