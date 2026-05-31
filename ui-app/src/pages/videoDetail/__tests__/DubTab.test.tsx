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
    onStop: vi.fn(),
    canStop: false,
    isStopping: false,
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

describe('DubTab — Stop button', () => {
  it('shows Generate when idle', () => {
    renderDubTab({ isGeneratingTts: false });
    expect(screen.getByRole('button', { name: /generate tts/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /stop/i })).not.toBeInTheDocument();
  });

  it('shows Stop while generating once the task_id is known', () => {
    renderDubTab({ isGeneratingTts: true, canStop: true });
    expect(screen.queryByRole('button', { name: /generate tts/i })).not.toBeInTheDocument();
    const stopBtn = screen.getByRole('button', { name: /stop tts/i }) as HTMLButtonElement;
    expect(stopBtn).toBeInTheDocument();
    expect(stopBtn.disabled).toBe(false);
  });

  it('disables Stop until the task_id lands (canStop=false)', () => {
    renderDubTab({ isGeneratingTts: true, canStop: false });
    const stopBtn = screen.getByRole('button', { name: /stop tts/i }) as HTMLButtonElement;
    expect(stopBtn.disabled).toBe(true);
  });

  it('disables Stop and shows "Stopping…" while a cancel is in flight', () => {
    renderDubTab({ isGeneratingTts: true, canStop: true, isStopping: true });
    const stopBtn = screen.getByRole('button', { name: /stop tts/i }) as HTMLButtonElement;
    expect(stopBtn.disabled).toBe(true);
    expect(stopBtn.textContent || '').toMatch(/stopping/i);
  });

  it('calls onStop when the Stop button is clicked', () => {
    const { props } = renderDubTab({ isGeneratingTts: true, canStop: true });
    fireEvent.click(screen.getByRole('button', { name: /stop tts/i }));
    expect(props.onStop).toHaveBeenCalled();
  });
});
