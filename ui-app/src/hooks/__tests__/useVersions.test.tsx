import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useVersions } from '../useVersions';

vi.mock('../../api/versions', () => ({
  getVersions: vi.fn(),
  createVersion: vi.fn(),
  renameVersion: vi.fn(),
  deleteVersion: vi.fn(),
  importVersion: vi.fn(),
}));

describe('useVersions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches versions on mount and exposes them', async () => {
    const { getVersions } = await import('../../api/versions');
    (getVersions as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 'v1', name: 'first', created_at: '2026-05-29T10:00:00Z' },
    ]);
    const { result } = renderHook(() => useVersions('vid1', 'vi'));
    await waitFor(() => expect(result.current.versions).toHaveLength(1));
    expect(result.current.versions[0].id).toBe('v1');
  });

  it('createSnapshot calls the API and refreshes', async () => {
    const api = await import('../../api/versions');
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    (api.createVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'v1', name: null, created_at: '2026-05-29T10:00:00Z',
    });
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: 'v1', name: null, created_at: '2026-05-29T10:00:00Z' },
    ]);

    const { result } = renderHook(() => useVersions('vid1', 'vi'));
    await waitFor(() => expect(result.current.versions).toEqual([]));

    await act(async () => {
      await result.current.createSnapshot(null);
    });

    expect(api.createVersion).toHaveBeenCalledWith('vid1', 'vi', null);
    await waitFor(() => expect(result.current.versions).toHaveLength(1));
  });

  it('rename calls the API and refreshes', async () => {
    const api = await import('../../api/versions');
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 'v1', name: null, created_at: '2026-05-29T10:00:00Z' },
    ]);
    (api.renameVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'v1', name: 'polished', created_at: '2026-05-29T10:00:00Z',
    });

    const { result } = renderHook(() => useVersions('vid1', 'vi'));
    await waitFor(() => expect(result.current.versions).toHaveLength(1));

    await act(async () => {
      await result.current.rename('v1', 'polished');
    });

    expect(api.renameVersion).toHaveBeenCalledWith('vid1', 'vi', 'v1', 'polished');
  });

  it('remove calls the API and refreshes', async () => {
    const api = await import('../../api/versions');
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: 'v1', name: null, created_at: '2026-05-29T10:00:00Z' },
    ]);
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    (api.deleteVersion as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);

    const { result } = renderHook(() => useVersions('vid1', 'vi'));
    await waitFor(() => expect(result.current.versions).toHaveLength(1));

    await act(async () => {
      await result.current.remove('v1');
    });

    expect(api.deleteVersion).toHaveBeenCalledWith('vid1', 'vi', 'v1');
    await waitFor(() => expect(result.current.versions).toHaveLength(0));
  });

  it('importFile calls the API and refreshes', async () => {
    const api = await import('../../api/versions');
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    (api.importVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'v1', name: null, created_at: '2026-05-30T10:00:00Z',
    });
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: 'v1', name: null, created_at: '2026-05-30T10:00:00Z' },
    ]);

    const { result } = renderHook(() => useVersions('vid1', 'vi'));
    await waitFor(() => expect(result.current.versions).toEqual([]));

    const file = new File(['srt content'], 'test.srt', { type: 'text/plain' });
    await act(async () => {
      await result.current.importFile(file, null);
    });

    expect(api.importVersion).toHaveBeenCalledWith('vid1', 'vi', file, null);
    await waitFor(() => expect(result.current.versions).toHaveLength(1));
  });
});
