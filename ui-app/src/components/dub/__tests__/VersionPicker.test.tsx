import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VersionPicker } from '../VersionPicker';
import type { VersionEntry } from '../../../api/types';

const versions: VersionEntry[] = [
  { id: 'v2', name: 'polished', created_at: '2026-05-29T11:00:00Z' },
  { id: 'v1', name: 'migrated', created_at: '2026-05-29T10:00:00Z' },
];

describe('VersionPicker', () => {
  it('always renders the Working Draft option first', () => {
    render(
      <VersionPicker
        versions={versions}
        value="draft"
        onChange={vi.fn()}
      />,
    );
    const options = screen.getAllByRole('option');
    expect(options[0].textContent).toMatch(/working draft/i);
  });

  it('renders each snapshot below the working draft', () => {
    render(
      <VersionPicker
        versions={versions}
        value="draft"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/polished/i)).toBeInTheDocument();
    expect(screen.getByText(/migrated/i)).toBeInTheDocument();
  });

  it('falls back to the id when a snapshot has no name', () => {
    render(
      <VersionPicker
        versions={[
          { id: 'v3', name: null, created_at: '2026-05-29T12:00:00Z' },
        ]}
        value="draft"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/v3/)).toBeInTheDocument();
  });

  it('calls onChange with the selected version id', () => {
    const onChange = vi.fn();
    render(
      <VersionPicker
        versions={versions}
        value="draft"
        onChange={onChange}
      />,
    );
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'v2' } });
    expect(onChange).toHaveBeenCalledWith('v2');
  });
});
