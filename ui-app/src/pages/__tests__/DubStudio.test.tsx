import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DubStudioPage } from '../DubStudio';
import * as standaloneDubApi from '../../api/standaloneDub';
import * as clientApi from '../../api/client';
import { saveFavorites } from '../../utils/favoriteVoices';

// ── mocks ────────────────────────────────────────────────────────────────────

vi.mock('../../api/standaloneDub', () => ({
  getStandaloneDubs: vi.fn().mockResolvedValue([]),
  postStandaloneDub: vi.fn(),
  deleteStandaloneDub: vi.fn().mockResolvedValue(undefined),
  getStandaloneDubUrl: (uuid: string) => `/api/standalone-dub/${uuid}.wav`,
}));

vi.mock('../../api/client', () => ({
  getTTSProviders: vi.fn().mockResolvedValue([
    { id: 'edge', name: 'Edge TTS', free: true, requires_key: false },
  ]),
  getTTSVoices: vi.fn().mockResolvedValue([
    { name: 'vi-VN-HoaiMyNeural', language: 'vi', gender: 'Female', provider: 'edge', friendly_name: 'Hoai My' },
  ]),
  subscribeSSE: vi.fn().mockReturnValue({ close: vi.fn() }),
}));

vi.mock('../../utils/storage', () => ({
  storageGet: vi.fn().mockReturnValue(''),
  storageSet: vi.fn(),
  loadApiKeys: vi.fn().mockReturnValue({
    anthropic: '',
    openai: '',
    deepseek: '',
    elevenlabs: '',
    google: '',
  }),
  loadLLMPrefs: vi.fn().mockReturnValue({ backend: 'deepseek', model: 'deepseek-chat' }),
}));

// ── helpers ───────────────────────────────────────────────────────────────────

function renderPage() {
  return render(
    <MemoryRouter>
      <DubStudioPage />
    </MemoryRouter>,
  );
}

// ── tests ─────────────────────────────────────────────────────────────────────

describe('DubStudioPage — empty recent state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(clientApi.getTTSProviders).mockResolvedValue([
      { id: 'edge', name: 'Edge TTS', free: true, requires_key: false },
    ]);
    vi.mocked(clientApi.getTTSVoices).mockResolvedValue([
      { name: 'vi-VN-HoaiMyNeural', language: 'vi', gender: 'Female', provider: 'edge', friendly_name: 'Hoai My' },
    ]);
    vi.mocked(standaloneDubApi.getStandaloneDubs).mockResolvedValue([]);
  });

  it('renders the page heading', async () => {
    renderPage();
    expect(screen.getByText(/dub studio/i)).toBeInTheDocument();
  });

  it('shows empty state text when no recent dubs', async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no dubs yet/i)).toBeInTheDocument(),
    );
  });
});

describe('DubStudioPage — seeded recent dubs', () => {
  const fakeDubs: standaloneDubApi.StandaloneDubEntry[] = [
    {
      uuid: 'abc-123',
      original_filename: 'test.srt',
      provider: 'edge',
      voice: 'vi-VN-HoaiMyNeural',
      language: 'vi',
      playback_speed: 1.0,
      enable_shortening: true,
      duration_seconds: 42,
      created_at: '2024-01-15T10:00:00Z',
      file_size_bytes: 1024000,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(clientApi.getTTSProviders).mockResolvedValue([
      { id: 'edge', name: 'Edge TTS', free: true, requires_key: false },
    ]);
    vi.mocked(clientApi.getTTSVoices).mockResolvedValue([]);
    vi.mocked(standaloneDubApi.getStandaloneDubs).mockResolvedValue(fakeDubs);
  });

  it('renders the filename of a seeded dub entry', async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/test\.srt/i)).toBeInTheDocument(),
    );
  });
});

describe('DubStudioPage — generate button guard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(clientApi.getTTSProviders).mockResolvedValue([
      { id: 'edge', name: 'Edge TTS', free: true, requires_key: false },
    ]);
    vi.mocked(clientApi.getTTSVoices).mockResolvedValue([]);
    vi.mocked(standaloneDubApi.getStandaloneDubs).mockResolvedValue([]);
  });

  it('Generate button is disabled when no SRT file is selected', async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.queryByText(/loading voices/i)).not.toBeInTheDocument(),
    );
    const btn = screen.getByRole('button', { name: /generate dub/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('DubStudioPage — delete flow', () => {
  const fakeDubs: standaloneDubApi.StandaloneDubEntry[] = [
    {
      uuid: 'del-456',
      original_filename: 'delete-me.srt',
      provider: 'edge',
      voice: 'vi-VN-HoaiMyNeural',
      language: 'vi',
      playback_speed: 1.0,
      enable_shortening: true,
      duration_seconds: 10,
      created_at: '2024-01-15T10:00:00Z',
      file_size_bytes: 512000,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(clientApi.getTTSProviders).mockResolvedValue([
      { id: 'edge', name: 'Edge TTS', free: true, requires_key: false },
    ]);
    vi.mocked(clientApi.getTTSVoices).mockResolvedValue([]);
    // First call returns the entry, second call (after delete) returns []
    vi.mocked(standaloneDubApi.getStandaloneDubs)
      .mockResolvedValueOnce(fakeDubs)
      .mockResolvedValue([]);
    vi.mocked(standaloneDubApi.deleteStandaloneDub).mockResolvedValue(undefined);
  });

  it('calls deleteStandaloneDub and refreshes the list', async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/delete-me\.srt/i)).toBeInTheDocument(),
    );

    const deleteBtn = screen.getByRole('button', { name: /delete/i });
    fireEvent.click(deleteBtn);

    await waitFor(() =>
      expect(standaloneDubApi.deleteStandaloneDub).toHaveBeenCalledWith('del-456'),
    );
  });
});

describe('DubStudioPage — favorites strip', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem('tts_favorite_voices_v1');
  });

  it('renders the favorites strip when a matching favorite exists', async () => {
    // Seed a favorite that matches what the page will load by default
    // (provider=google, language=vi after the auto-correct effect).
    saveFavorites([
      {
        provider: 'google',
        voice: 'vi-VN-Wavenet-A',
        language: 'vi',
        nickname: 'Sarah',
      },
    ]);
    // Make the voice list include that voice so the friendly-name fallback
    // path isn't hit; the chip should still show "Sarah" (nickname wins).
    // Also mock getTTSProviders to include 'google' so the auto-correct effect
    // doesn't switch provider away from google (which would drop the scoped favorite).
    const api = await import('../../api/client');
    (api.getTTSProviders as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 'google', name: 'Google TTS', free: false, requires_key: true },
    ]);
    (api.getTTSVoices as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        name: 'vi-VN-Wavenet-A',
        friendly_name: 'Vietnamese Wavenet A',
        gender: 'FEMALE',
        language: 'vi',
        provider: 'google',
      },
    ]);
    const stdApi = await import('../../api/standaloneDub');
    (stdApi.getStandaloneDubs as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText('Sarah')).toBeInTheDocument();
  });
});
