import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SegmentList } from '../SegmentList';
import type { SubtitleSegment } from '../../../api/types';

function makeSegments(): SubtitleSegment[] {
  return [
    { id: 1, startTime: '00:00:00,000', endTime: '00:00:04,000', text: 'first' },
    { id: 2, startTime: '00:00:05,000', endTime: '00:00:08,000', text: 'second' },
    { id: 3, startTime: '00:00:09,000', endTime: '00:00:12,000', text: 'third' },
  ];
}

function renderList(overrides: Partial<React.ComponentProps<typeof SegmentList>> = {}) {
  const props = {
    segments: makeSegments(),
    currentTime: 0,
    onSeek: vi.fn(),
    onUpdate: vi.fn(),
    onDelete: vi.fn(),
    onSplit: vi.fn(),
    onMerge: vi.fn(),
    onAdd: vi.fn(),
    ...overrides,
  };
  return { ...render(<SegmentList {...props} />), props };
}

describe('SegmentList — click does not seek', () => {
  it('clicking the start time input does not call onSeek', () => {
    const { props } = renderList();
    const startInput = screen.getAllByDisplayValue('00:00:00,000')[0];
    fireEvent.click(startInput);
    expect(props.onSeek).not.toHaveBeenCalled();
  });

  it('clicking the end time input does not call onSeek', () => {
    const { props } = renderList();
    const endInput = screen.getAllByDisplayValue('00:00:04,000')[0];
    fireEvent.click(endInput);
    expect(props.onSeek).not.toHaveBeenCalled();
  });

  it('clicking the text area does not call onSeek', () => {
    const { props } = renderList();
    const textarea = screen.getByDisplayValue('first');
    fireEvent.click(textarea);
    expect(props.onSeek).not.toHaveBeenCalled();
  });

  it('clicking the # index label still seeks to the segment start', () => {
    const { props } = renderList();
    const label = screen.getAllByTitle(/jump video to this segment/i)[0];
    fireEvent.click(label);
    expect(props.onSeek).toHaveBeenCalledWith(0);
  });
});
