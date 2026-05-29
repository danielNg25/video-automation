import { useEffect, useRef, useCallback, useState } from 'react';
import type { SubtitleSegment } from '../../api/types';
import { srtTimestampToSeconds, isValidSrtTimestamp } from '../../utils/srtTime';

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

interface TimestampInputProps {
  /** Committed timestamp value (HH:MM:SS,mmm). */
  value: string;
  /** Returns true if the parent accepts the new value, false if it rejects (e.g. start>=end). */
  onCommit: (next: string) => boolean;
}

function TimestampInput({ value, onCommit }: TimestampInputProps) {
  const [committedValue, setCommittedValue] = useState(value);
  const [local, setLocal] = useState(value);
  const [invalid, setInvalid] = useState(false);

  // Re-sync when an external change to `value` lands (e.g. a sibling commit
  // shifted this segment's bounds). Uses the React "adjust state during
  // render" pattern instead of useEffect.
  if (committedValue !== value) {
    setCommittedValue(value);
    setLocal(value);
    setInvalid(false);
  }

  const commit = useCallback(() => {
    if (local === committedValue) return; // no pending change to commit
    if (!isValidSrtTimestamp(local)) {
      setLocal(committedValue);
      setInvalid(false);
      return;
    }
    const accepted = onCommit(local);
    if (accepted) {
      setCommittedValue(local);
    } else {
      setLocal(committedValue);
      setInvalid(false);
    }
  }, [local, committedValue, onCommit]);

  const baseClasses =
    'font-mono text-[10px] bg-transparent border rounded px-1 py-0.5 w-[100px] text-on-surface focus:outline-none';
  const stateClasses = invalid
    ? 'border-red-400/60 focus:border-red-400'
    : 'border-outline-variant/15 focus:border-primary';

  return (
    <input
      className={`${baseClasses} ${stateClasses}`}
      value={local}
      onChange={(e) => {
        const next = e.target.value;
        setLocal(next);
        setInvalid(next.length > 0 && !isValidSrtTimestamp(next));
      }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          commit();
        } else if (e.key === 'Escape') {
          setLocal(committedValue);
          setInvalid(false);
          (e.target as HTMLInputElement).blur();
        }
      }}
      title={invalid ? 'Format: HH:MM:SS,mmm' : undefined}
    />
  );
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

  const activeIndex = segments.findIndex((seg) => {
    const start = srtTimestampToSeconds(seg.startTime);
    const end = srtTimestampToSeconds(seg.endTime);
    return currentTime >= start && currentTime < end;
  });

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

  const commitStart = useCallback(
    (i: number) => (next: string): boolean => {
      const start = srtTimestampToSeconds(next);
      const end = srtTimestampToSeconds(segments[i].endTime);
      if (start >= end) return false;
      onUpdate(i, { ...segments[i], startTime: next });
      return true;
    },
    [segments, onUpdate],
  );

  const commitEnd = useCallback(
    (i: number) => (next: string): boolean => {
      const start = srtTimestampToSeconds(segments[i].startTime);
      const end = srtTimestampToSeconds(next);
      if (start >= end) return false;
      onUpdate(i, { ...segments[i], endTime: next });
      return true;
    },
    [segments, onUpdate],
  );

  return (
    <div ref={listRef} className="flex-1 overflow-y-auto pr-1">
      <div className="space-y-1">
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
            <div className="flex items-center gap-2 mb-1.5">
              <span
                className="font-mono text-[9px] text-on-surface-variant w-5 text-right cursor-pointer hover:text-primary"
                onClick={() => onSeek(startSec)}
                title="Click to jump video to this segment"
              >
                {i + 1}
              </span>
              <TimestampInput value={seg.startTime} onCommit={commitStart(i)} />
              <span className="text-[9px] text-on-surface-variant">→</span>
              <TimestampInput value={seg.endTime} onCommit={commitEnd(i)} />

              <div className="flex-1" />
              <div
                className={`flex gap-0.5 transition-opacity ${
                  isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                }`}
              >
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

            <textarea
              className="w-full bg-transparent text-xs text-on-surface resize-none border-none outline-none leading-relaxed min-h-[1.5em]"
              value={seg.text}
              rows={Math.max(1, seg.text.split('\n').length)}
              onChange={(e) => onUpdate(i, { ...seg, text: e.target.value })}
            />
          </div>
        );
      })}
      </div>

      <div className="pt-2 pb-1">
        <button
          type="button"
          onClick={() => onAdd(segments.length - 1)}
          className="w-full py-2 text-xs rounded-lg border border-dashed border-primary/40 text-primary/80 hover:border-primary hover:text-primary hover:bg-primary/5 transition-colors"
        >
          + Add subtitle
        </button>
      </div>
    </div>
  );
}
