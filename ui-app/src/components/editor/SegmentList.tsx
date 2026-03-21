import { useEffect, useRef, useCallback } from 'react';
import type { SubtitleSegment } from '../../api/types';
import { srtTimestampToSeconds, secondsToSrtTimestamp, isValidSrtTimestamp } from '../../utils/srtTime';

interface SegmentListProps {
  segments: SubtitleSegment[];
  currentTime: number;
  onSeek: (time: number) => void;
  onUpdate: (index: number, segment: SubtitleSegment) => void;
  onDelete: (index: number) => void;
  onSplit: (index: number, splitTime: number) => void;
  onMerge: (index: number) => void;
  onAdd: (afterIndex: number) => void;
}

export function SegmentList({
  segments,
  currentTime,
  onSeek,
  onUpdate,
  onDelete,
  onSplit,
  onMerge,
  onAdd,
}: SegmentListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);

  // Find active segment index
  const activeIndex = segments.findIndex((seg) => {
    const start = srtTimestampToSeconds(seg.startTime);
    const end = srtTimestampToSeconds(seg.endTime);
    return currentTime >= start && currentTime < end;
  });

  // Auto-scroll to active segment
  useEffect(() => {
    if (activeRef.current && listRef.current) {
      const container = listRef.current;
      const el = activeRef.current;
      const elTop = el.offsetTop - container.offsetTop;
      const elBottom = elTop + el.offsetHeight;
      const viewTop = container.scrollTop;
      const viewBottom = viewTop + container.clientHeight;

      if (elTop < viewTop || elBottom > viewBottom) {
        el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }, [activeIndex]);

  const handleTimestampBlur = useCallback(
    (index: number, field: 'startTime' | 'endTime', value: string) => {
      if (!isValidSrtTimestamp(value)) return;
      const seg = segments[index];
      const updated = { ...seg, [field]: value };

      // Validate: start < end
      const start = srtTimestampToSeconds(updated.startTime);
      const end = srtTimestampToSeconds(updated.endTime);
      if (start >= end) return;

      onUpdate(index, updated);
    },
    [segments, onUpdate],
  );

  return (
    <div ref={listRef} className="flex-1 overflow-y-auto space-y-1 pr-1">
      {segments.length === 0 && (
        <div className="text-center text-on-surface-variant text-xs py-8">
          No subtitle segments
        </div>
      )}

      {segments.map((seg, i) => {
        const isActive = i === activeIndex;
        const startSec = srtTimestampToSeconds(seg.startTime);

        return (
          <div
            key={seg.id}
            ref={isActive ? activeRef : undefined}
            className={`group rounded-lg border px-3 py-2 transition-colors ${
              isActive
                ? 'border-primary/40 bg-primary/5'
                : 'border-outline-variant/10 bg-surface-container-lowest hover:border-outline-variant/20'
            }`}
          >
            {/* Header: index + timestamps */}
            <div className="flex items-center gap-2 mb-1.5">
              <span
                className="font-mono text-[9px] text-on-surface-variant w-5 text-right cursor-pointer hover:text-primary"
                onClick={() => onSeek(startSec)}
                title="Jump to segment"
              >
                {i + 1}
              </span>
              <input
                className="font-mono text-[10px] bg-transparent border border-outline-variant/15 rounded px-1 py-0.5 w-[100px] text-on-surface focus:border-primary focus:outline-none"
                defaultValue={seg.startTime}
                onBlur={(e) => handleTimestampBlur(i, 'startTime', e.target.value)}
                onClick={() => onSeek(srtTimestampToSeconds(seg.startTime))}
              />
              <span className="text-[9px] text-on-surface-variant">→</span>
              <input
                className="font-mono text-[10px] bg-transparent border border-outline-variant/15 rounded px-1 py-0.5 w-[100px] text-on-surface focus:border-primary focus:outline-none"
                defaultValue={seg.endTime}
                onBlur={(e) => handleTimestampBlur(i, 'endTime', e.target.value)}
              />

              {/* Action buttons (visible on hover) */}
              <div className="flex-1" />
              <div className="opacity-0 group-hover:opacity-100 flex gap-0.5 transition-opacity">
                <button
                  onClick={() => onSplit(i, currentTime)}
                  className="p-0.5 rounded hover:bg-primary/10 text-on-surface-variant hover:text-primary"
                  title="Split at playhead"
                >
                  <span className="material-symbols-outlined text-[14px]">content_cut</span>
                </button>
                {i < segments.length - 1 && (
                  <button
                    onClick={() => onMerge(i)}
                    className="p-0.5 rounded hover:bg-primary/10 text-on-surface-variant hover:text-primary"
                    title="Merge with next"
                  >
                    <span className="material-symbols-outlined text-[14px]">merge</span>
                  </button>
                )}
                <button
                  onClick={() => onAdd(i)}
                  className="p-0.5 rounded hover:bg-primary/10 text-on-surface-variant hover:text-primary"
                  title="Add segment after"
                >
                  <span className="material-symbols-outlined text-[14px]">add</span>
                </button>
                <button
                  onClick={() => onDelete(i)}
                  className="p-0.5 rounded hover:bg-red-500/10 text-on-surface-variant hover:text-red-400"
                  title="Delete segment"
                >
                  <span className="material-symbols-outlined text-[14px]">delete</span>
                </button>
              </div>
            </div>

            {/* Text editor */}
            <textarea
              className="w-full bg-transparent text-xs text-on-surface resize-none border-none outline-none leading-relaxed min-h-[1.5em]"
              value={seg.text}
              rows={Math.max(1, seg.text.split('\n').length)}
              onChange={(e) => onUpdate(i, { ...seg, text: e.target.value })}
              onClick={() => onSeek(startSec)}
            />
          </div>
        );
      })}
    </div>
  );
}
