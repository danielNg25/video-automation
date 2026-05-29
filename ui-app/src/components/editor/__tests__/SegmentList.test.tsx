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

describe('SegmentList — time inputs are controlled with validation feedback', () => {
  it('typing updates the input value live (no defaultValue snap-back)', () => {
    renderList();
    const input = screen.getAllByDisplayValue('00:00:00,000')[0] as HTMLInputElement;
    fireEvent.change(input, { target: { value: '00:00:01,500' } });
    expect(input.value).toBe('00:00:01,500');
  });

  it('typing an invalid format adds an error border class', () => {
    renderList();
    const input = screen.getAllByDisplayValue('00:00:00,000')[0] as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'not-a-time' } });
    expect(input.className).toMatch(/border-red-400/);
  });

  it('blur with a valid format calls onUpdate once', () => {
    const { props } = renderList();
    const input = screen.getAllByDisplayValue('00:00:00,000')[0] as HTMLInputElement;
    fireEvent.change(input, { target: { value: '00:00:01,500' } });
    fireEvent.blur(input);
    expect(props.onUpdate).toHaveBeenCalledTimes(1);
    expect(props.onUpdate).toHaveBeenCalledWith(
      0,
      expect.objectContaining({ startTime: '00:00:01,500' }),
    );
  });

  it('blur with an invalid format reverts the value and does not call onUpdate', () => {
    const { props } = renderList();
    const input = screen.getAllByDisplayValue('00:00:00,000')[0] as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'garbage' } });
    fireEvent.blur(input);
    expect(props.onUpdate).not.toHaveBeenCalled();
    expect(input.value).toBe('00:00:00,000');
  });

  it('blur with start >= end is rejected and reverts the value', () => {
    const { props } = renderList();
    const input = screen.getAllByDisplayValue('00:00:00,000')[0] as HTMLInputElement;
    fireEvent.change(input, { target: { value: '00:00:05,000' } });
    fireEvent.blur(input);
    expect(props.onUpdate).not.toHaveBeenCalled();
    expect(input.value).toBe('00:00:00,000');
  });

  it('Enter key commits a valid value (same as blur)', () => {
    const { props } = renderList();
    const input = screen.getAllByDisplayValue('00:00:00,000')[0] as HTMLInputElement;
    fireEvent.change(input, { target: { value: '00:00:01,500' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(props.onUpdate).toHaveBeenCalledTimes(1);
  });

  it('Escape key reverts the in-progress edit', () => {
    const { props } = renderList();
    const input = screen.getAllByDisplayValue('00:00:00,000')[0] as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'whatever' } });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(input.value).toBe('00:00:00,000');
    expect(props.onUpdate).not.toHaveBeenCalled();
  });

  it('Enter does not double-commit when the input is focused', () => {
    const { props } = renderList();
    const input = screen.getAllByDisplayValue('00:00:00,000')[0] as HTMLInputElement;
    input.focus();
    fireEvent.change(input, { target: { value: '00:00:01,500' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.blur(input);
    expect(props.onUpdate).toHaveBeenCalledTimes(1);
  });
});

describe('SegmentList — toolbar visibility', () => {
  it('on the active row, the toolbar wrapper does not use the opacity-0 hover gate', () => {
    // currentTime = 1.0 falls inside segment 1 (00:00:00 → 00:00:04). That row is active.
    renderList({ currentTime: 1.0 });
    const addBtn = screen.getAllByTitle(/add segment after/i)[0];
    const toolbar = addBtn.parentElement!;
    expect(toolbar.className).not.toMatch(/opacity-0/);
  });

  it('on an inactive row, the toolbar still uses opacity-0 / group-hover', () => {
    // currentTime = 1.0 → segment 2 (at index 1) is inactive.
    renderList({ currentTime: 1.0 });
    const addBtns = screen.getAllByTitle(/add segment after/i);
    // addBtns[1] is the second row's add button (inactive).
    const inactiveToolbar = addBtns[1].parentElement!;
    expect(inactiveToolbar.className).toMatch(/opacity-0/);
    expect(inactiveToolbar.className).toMatch(/group-hover:opacity-100/);
  });
});

describe('SegmentList — sticky "+ Add subtitle" button', () => {
  it('with a non-empty list, the bottom button calls onAdd(segments.length - 1)', () => {
    const { props } = renderList(); // 3 segments
    const btn = screen.getByRole('button', { name: /add subtitle/i });
    fireEvent.click(btn);
    expect(props.onAdd).toHaveBeenCalledWith(2);
  });

  it('with an empty list, the bottom button calls onAdd(-1)', () => {
    const { props } = renderList({ segments: [] });
    const btn = screen.getByRole('button', { name: /add subtitle/i });
    fireEvent.click(btn);
    expect(props.onAdd).toHaveBeenCalledWith(-1);
  });

  it('the per-row "Add segment after" hover button still calls onAdd(i)', () => {
    const { props } = renderList({ currentTime: 1.0 }); // segment 0 is active
    // The active-row toolbar is now always visible (Task 3), so we can
    // click the per-row + button without simulating hover.
    const perRow = screen.getAllByTitle(/add segment after/i)[0];
    fireEvent.click(perRow);
    expect(props.onAdd).toHaveBeenCalledWith(0);
  });
});
