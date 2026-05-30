import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EditorTab } from '../EditorTab';

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}));

// Mock the API surface the editor pulls from. All four endpoints are
// awaited on mount, so each test seeds the relevant mock.
vi.mock('../../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../../api/client')>(
    '../../../api/client',
  );
  return {
    ...actual,
    getVideo: vi.fn(),
    getSrt: vi.fn(),
    getTTSList: vi.fn(),
    getRawVideoUrl: (id: string) => `/raw/${id}`,
    getSrtDownloadUrl: (id: string, lang: string) => `/srt/${id}/${lang}`,
    getProxyVideoUrl: (id: string) => `/proxy/${id}`,
    getTTSAudioUrl: (id: string, lang: string, file: string) => `/tts/${id}/${lang}?file=${file}`,
    putSrt: vi.fn(),
  };
});

const videoMeta = {
  id: 'vid1',
  title: 'Test video',
  url: '',
  source: 'douyin',
  duration: 30,
  status: 'completed',
  created_at: 0,
  srt_languages: ['vi', 'en'],
  has_video: true,
  tts_provider: null,
  tts_voice: null,
};

const baseProps: React.ComponentProps<typeof EditorTab> = {
  videoId: 'vid1',
  initialVideo: videoMeta as never,
  versions: [
    { id: 'v1', name: 'first cut', created_at: '2026-05-30T10:00:00Z' },
    { id: 'v2', name: null, created_at: '2026-05-30T11:00:00Z' },
  ],
  onCreateSnapshot: vi.fn(),
  onRenameVersion: vi.fn(),
  onDeleteVersion: vi.fn(),
  onImportVersion: vi.fn(),
  activeLang: 'vi',
  onActiveLangChange: vi.fn(),
};

const sampleSegments = [
  { id: 1, startTime: '00:00:00,000', endTime: '00:00:02,000', text: 'hello' },
];

const sampleDubs = [
  {
    filename: 'vid1_vi_v1_google_voiceA.wav',
    language: 'vi',
    provider: 'google',
    voice: 'voiceA',
    version: 'v1',
    size: 1024,
    created_at: 1700000000,
  },
  {
    filename: 'vid1_en_v1_google_voiceB.wav',
    language: 'en',
    provider: 'google',
    voice: 'voiceB',
    version: 'v1',
    size: 1024,
    created_at: 1700000001,
  },
];

beforeEach(async () => {
  const api = await import('../../../api/client');
  vi.mocked(api.getVideo).mockResolvedValue(videoMeta as never);
  vi.mocked(api.getSrt).mockResolvedValue({ language: 'vi', segments: sampleSegments } as never);
  vi.mocked(api.getTTSList).mockResolvedValue(sampleDubs as never);
});

describe('EditorTab — subtitle version + dub pickers', () => {
  it('renders both pickers and the dub list is filtered to the active language', async () => {
    render(<EditorTab {...baseProps} />);

    const versionSelect = await screen.findByLabelText(/subtitle version/i);
    expect((versionSelect as HTMLSelectElement).value).toBe('draft');
    // Working draft + v1 + v2.
    expect(versionSelect.querySelectorAll('option').length).toBe(3);

    const dubSelect = await screen.findByLabelText(/dub audio/i);
    // Wait for the dub list to land.
    await waitFor(() => {
      // 'Source audio' + the one Vietnamese dub. The English dub is filtered out.
      expect(dubSelect.querySelectorAll('option').length).toBe(2);
    });
  });

  it('picking a version reloads the SRT with that version', async () => {
    const api = await import('../../../api/client');
    render(<EditorTab {...baseProps} />);

    // First load is for the working draft.
    await waitFor(() => expect(api.getSrt).toHaveBeenCalledWith('vid1', 'vi', 'draft'));

    const versionSelect = await screen.findByLabelText(/subtitle version/i);
    fireEvent.change(versionSelect, { target: { value: 'v1' } });

    await waitFor(() => expect(api.getSrt).toHaveBeenCalledWith('vid1', 'vi', 'v1'));
  });

  it('shows a preview banner and disables Save / Save-as-version / Import while previewing', async () => {
    render(<EditorTab {...baseProps} />);

    const versionSelect = await screen.findByLabelText(/subtitle version/i);
    fireEvent.change(versionSelect, { target: { value: 'v2' } });

    expect(await screen.findByText(/previewing/i)).toBeInTheDocument();
    // Save / Save-as-version both render an icon span and a label; the
    // accessible name includes the icon text, so anchor on the end.
    const saveBtn = screen.getAllByRole('button').find((b) => /save\s*$/i.test(b.textContent || ''));
    expect((saveBtn as HTMLButtonElement | undefined)?.disabled).toBe(true);
    expect((screen.getByRole('button', { name: /save as version/i }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: /import srt/i }) as HTMLButtonElement).disabled).toBe(true);

    // The "switch to working draft" affordance returns to edit mode.
    fireEvent.click(screen.getByRole('button', { name: /switch to working draft/i }));
    await waitFor(() => {
      expect(screen.queryByText(/previewing/i)).not.toBeInTheDocument();
    });
  });

  it('switching languages resets the version + dub pickers', async () => {
    const api = await import('../../../api/client');
    const { rerender } = render(<EditorTab {...baseProps} />);

    const versionSelect = await screen.findByLabelText(/subtitle version/i);
    fireEvent.change(versionSelect, { target: { value: 'v1' } });
    await waitFor(() => expect(api.getSrt).toHaveBeenCalledWith('vid1', 'vi', 'v1'));

    // Parent flips the language.
    rerender(<EditorTab {...baseProps} activeLang="en" />);

    await waitFor(() => {
      // After the language change, the editor reloads the working draft for 'en',
      // not v1 (v1 was a Vietnamese version).
      expect(api.getSrt).toHaveBeenCalledWith('vid1', 'en', 'draft');
    });
    expect((screen.getByLabelText(/subtitle version/i) as HTMLSelectElement).value).toBe('draft');
  });
});
