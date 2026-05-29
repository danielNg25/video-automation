import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DubTab } from '../DubTab';

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}));

function renderDubTab(overrides: Partial<React.ComponentProps<typeof DubTab>> = {}) {
  const props: React.ComponentProps<typeof DubTab> = {
    videoId: 'test-video-id',
    versions: [],
    selectedVersion: 'draft',
    onVersionChange: vi.fn(),
    ttsProviders: [],
    selectedTtsProvider: 'google',
    onChangeTtsProvider: vi.fn(),
    ttsVoices: [],
    selectedVoiceId: '',
    onChangeSelectedVoiceId: vi.fn(),
    voiceIdInput: '',
    onChangeVoiceIdInput: vi.fn(),
    voiceIdSaved: false,
    onSaveVoiceId: vi.fn(),
    ttsApiKey: '',
    onChangeTtsApiKey: vi.fn(),
    ttsLanguage: 'vi',
    onChangeTtsLanguage: vi.fn(),
    availableTtsLanguages: ['vi', 'en'],
    playbackSpeed: 1.5,
    onChangePlaybackSpeed: vi.fn(),
    underlayDb: -12,
    onChangeUnderlayDb: vi.fn(),
    useDirectVoice: false,
    onChangeUseDirectVoice: vi.fn(),
    isGeneratingTts: false,
    ttsProgress: { pct: 0, message: '' },
    ttsGenerated: false,
    ttsError: '',
    ttsList: [],
    onReloadTtsList: vi.fn(),
    onGenerate: vi.fn(),
    llmBackend: '',
    llmApiKey: '',
    enableShortening: true,
    onChangeEnableShortening: vi.fn(),
    ...overrides,
  };
  return { ...render(<DubTab {...props} />), props };
}

describe('DubTab — shorten-to-fit checkbox', () => {
  it('reflects the enableShortening prop on render', () => {
    renderDubTab({ enableShortening: false });
    const box = screen.getByRole('checkbox', { name: /shorten dub to fit/i }) as HTMLInputElement;
    expect(box.checked).toBe(false);
  });

  it('renders checked when enableShortening is true', () => {
    renderDubTab({ enableShortening: true });
    const box = screen.getByRole('checkbox', { name: /shorten dub to fit/i }) as HTMLInputElement;
    expect(box.checked).toBe(true);
  });

  it('calls onChangeEnableShortening with the new boolean on click', () => {
    const { props } = renderDubTab({ enableShortening: true });
    const box = screen.getByRole('checkbox', { name: /shorten dub to fit/i });
    fireEvent.click(box);
    expect(props.onChangeEnableShortening).toHaveBeenCalledWith(false);
  });
});
