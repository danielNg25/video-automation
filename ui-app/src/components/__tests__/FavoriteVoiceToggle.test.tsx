import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { FavoriteVoiceToggle } from '../FavoriteVoiceToggle';
import { saveFavorites } from '../../utils/favoriteVoices';

const KEY = 'tts_favorite_voices_v1';

afterEach(() => {
  localStorage.removeItem(KEY);
});

describe('FavoriteVoiceToggle', () => {
  it('renders the outlined star when the voice is not favorited', () => {
    render(
      <FavoriteVoiceToggle provider="google" voice="v1" language="vi" />,
    );
    expect(screen.getByText('star_outline')).toBeInTheDocument();
  });

  it('renders the filled star when the voice IS favorited', () => {
    saveFavorites([{ provider: 'google', voice: 'v1', language: 'vi' }]);
    render(
      <FavoriteVoiceToggle provider="google" voice="v1" language="vi" />,
    );
    expect(screen.getByText('star')).toBeInTheDocument();
  });

  it('click toggles localStorage and fires onChange', () => {
    const onChange = vi.fn();
    render(
      <FavoriteVoiceToggle
        provider="google"
        voice="v1"
        language="vi"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /favorite/i }));
    expect(onChange).toHaveBeenCalledTimes(1);
    const stored = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({ provider: 'google', voice: 'v1', language: 'vi' });
  });

  it('disabled when voice is empty', () => {
    render(
      <FavoriteVoiceToggle provider="google" voice="" language="vi" />,
    );
    const btn = screen.getByRole('button', { name: /favorite/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
