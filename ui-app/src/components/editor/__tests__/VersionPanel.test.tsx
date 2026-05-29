import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VersionPanel } from '../VersionPanel';
import type { VersionEntry } from '../../../api/types';

const versions: VersionEntry[] = [
  { id: 'v2', name: 'polished', created_at: '2026-05-29T11:00:00Z' },
  { id: 'v1', name: null, created_at: '2026-05-29T10:00:00Z' },
];

describe('VersionPanel', () => {
  it('renders nothing when versions is empty', () => {
    const { container } = render(
      <VersionPanel versions={[]} onRename={vi.fn()} onDelete={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders one row per version', () => {
    render(
      <VersionPanel versions={versions} onRename={vi.fn()} onDelete={vi.fn()} />,
    );
    expect(screen.getByText(/v2/)).toBeInTheDocument();
    expect(screen.getByText(/v1/)).toBeInTheDocument();
  });

  it('inline-edit triggers onRename on blur with the new name', () => {
    const onRename = vi.fn();
    render(
      <VersionPanel versions={versions} onRename={onRename} onDelete={vi.fn()} />,
    );
    fireEvent.click(screen.getByText(/polished/i));
    const input = screen.getByDisplayValue('polished') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'final' } });
    fireEvent.blur(input);
    expect(onRename).toHaveBeenCalledWith('v2', 'final');
  });

  it('delete button calls onDelete with the version id', () => {
    const onDelete = vi.fn();
    render(
      <VersionPanel versions={versions} onRename={vi.fn()} onDelete={onDelete} />,
    );
    const deleteButtons = screen.getAllByTitle(/delete/i);
    fireEvent.click(deleteButtons[0]); // first row = v2
    expect(onDelete).toHaveBeenCalledWith('v2');
  });

  it('shows (no name) placeholder for entries without a name', () => {
    render(
      <VersionPanel versions={versions} onRename={vi.fn()} onDelete={vi.fn()} />,
    );
    expect(screen.getByText(/\(no name\)/i)).toBeInTheDocument();
  });
});
