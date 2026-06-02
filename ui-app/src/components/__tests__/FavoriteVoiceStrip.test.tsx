import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { FavoriteVoiceStrip } from '../FavoriteVoiceStrip';
import type { FavoriteVoice } from '../../utils/favoriteVoices';
import type { VoiceInfo } from '../../api/types';

const fav = (overrides: Partial<FavoriteVoice> = {}): FavoriteVoice => ({
  provider: 'google',
  voice: 'vi-VN-Wavenet-A',
  language: 'vi',
  ...overrides,
});

const voiceInfo = (overrides: Partial<VoiceInfo> = {}): VoiceInfo => ({
  name: 'vi-VN-Wavenet-A',
  language: 'vi',
  gender: 'FEMALE',
  provider: 'google',
  friendly_name: 'Vietnamese Wavenet A (Female)',
  ...overrides,
});

const noop = () => {};

describe('FavoriteVoiceStrip', () => {
  it('renders nothing with empty favorites', () => {
    const { container } = render(
      <FavoriteVoiceStrip
        favorites={[]}
        voices={[]}
        selectedVoiceId=""
        onPick={noop}
        onRemove={noop}
        onRename={noop}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders a chip with the nickname when set', () => {
    render(
      <FavoriteVoiceStrip
        favorites={[fav({ nickname: 'Sarah' })]}
        voices={[voiceInfo()]}
        selectedVoiceId=""
        onPick={noop}
        onRemove={noop}
        onRename={noop}
      />,
    );
    expect(screen.getByText('Sarah')).toBeInTheDocument();
  });

  it('renders a chip with the friendly_name when no nickname is set', () => {
    render(
      <FavoriteVoiceStrip
        favorites={[fav()]}
        voices={[voiceInfo()]}
        selectedVoiceId=""
        onPick={noop}
        onRemove={noop}
        onRename={noop}
      />,
    );
    expect(screen.getByText('Vietnamese Wavenet A (Female)')).toBeInTheDocument();
  });

  it('renders a chip with the voice id when no nickname and no friendly_name available', () => {
    render(
      <FavoriteVoiceStrip
        favorites={[fav()]}
        voices={[]} // empty — the friendly-name lookup fails
        selectedVoiceId=""
        onPick={noop}
        onRemove={noop}
        onRename={noop}
      />,
    );
    expect(screen.getByText('vi-VN-Wavenet-A')).toBeInTheDocument();
  });

  it('fires onPick with the voice id when the chip body is clicked', () => {
    const onPick = vi.fn();
    render(
      <FavoriteVoiceStrip
        favorites={[fav()]}
        voices={[voiceInfo()]}
        selectedVoiceId=""
        onPick={onPick}
        onRemove={noop}
        onRename={noop}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /pick vi-VN-Wavenet-A/i }));
    expect(onPick).toHaveBeenCalledWith('vi-VN-Wavenet-A');
  });

  it('fires onRemove with the full favorite when × is clicked', () => {
    const onRemove = vi.fn();
    render(
      <FavoriteVoiceStrip
        favorites={[fav({ nickname: 'Sarah' })]}
        voices={[voiceInfo()]}
        selectedVoiceId=""
        onPick={noop}
        onRemove={onRemove}
        onRename={noop}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /remove vi-VN-Wavenet-A/i }));
    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledWith(fav({ nickname: 'Sarah' }));
  });

  it('× click does not also fire onPick', () => {
    const onPick = vi.fn();
    const onRemove = vi.fn();
    render(
      <FavoriteVoiceStrip
        favorites={[fav()]}
        voices={[voiceInfo()]}
        selectedVoiceId=""
        onPick={onPick}
        onRemove={onRemove}
        onRename={noop}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /remove vi-VN-Wavenet-A/i }));
    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onPick).not.toHaveBeenCalled();
  });

  it('pencil click opens prompt and fires onRename with the trimmed value', () => {
    const onRename = vi.fn();
    const promptMock = vi.fn(() => '  Renamed  ');
    vi.stubGlobal('prompt', promptMock);
    render(
      <FavoriteVoiceStrip
        favorites={[fav()]}
        voices={[voiceInfo()]}
        selectedVoiceId=""
        onPick={noop}
        onRemove={noop}
        onRename={onRename}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /rename vi-VN-Wavenet-A/i }));
    expect(onRename).toHaveBeenCalledWith(fav(), 'Renamed');
    expect(promptMock).toHaveBeenCalledWith('Nickname (leave blank to clear)', '');
    vi.unstubAllGlobals();
  });

  it('pencil cancel (prompt returns null) is a no-op', () => {
    const onRename = vi.fn();
    vi.stubGlobal('prompt', vi.fn(() => null));
    render(
      <FavoriteVoiceStrip
        favorites={[fav({ nickname: 'Sarah' })]}
        voices={[voiceInfo()]}
        selectedVoiceId=""
        onPick={noop}
        onRemove={noop}
        onRename={onRename}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /rename vi-VN-Wavenet-A/i }));
    expect(onRename).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('the chip matching selectedVoiceId gets the highlight tint', () => {
    render(
      <FavoriteVoiceStrip
        favorites={[fav()]}
        voices={[voiceInfo()]}
        selectedVoiceId="vi-VN-Wavenet-A"
        onPick={noop}
        onRemove={noop}
        onRename={noop}
      />,
    );
    const chip = screen.getByRole('button', { name: /pick vi-VN-Wavenet-A/i });
    expect(chip.className).toMatch(/bg-primary\/15/);
    expect(chip.className).toMatch(/text-primary/);
  });
});
