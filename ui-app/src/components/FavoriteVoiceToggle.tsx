import { useState } from 'react';
import { isFavorite, toggleFavorite } from '../utils/favoriteVoices';

interface Props {
  provider: string;
  voice: string;
  language: string;
  /** Forced disabled state (overrides the auto-disable when voice is empty). */
  disabled?: boolean;
  /** Optional callback fired after the toggle persists. Parents use it to
   *  re-read favorites and refresh the strip below the dropdown. */
  onChange?: () => void;
}

export function FavoriteVoiceToggle({
  provider,
  voice,
  language,
  disabled,
  onChange,
}: Props) {
  // Local tick that increments on every toggle so isFavorite re-evaluates
  // without the parent having to manage the bool.
  const [, setTick] = useState(0);
  const isOn = voice ? isFavorite({ provider, voice, language }) : false;
  const isDisabled = disabled || !voice;

  return (
    <button
      type="button"
      disabled={isDisabled}
      aria-label={isOn ? 'Unfavorite voice' : 'Favorite voice'}
      title={isOn ? 'Remove from favorites' : 'Add to favorites'}
      onClick={() => {
        toggleFavorite({ provider, voice, language });
        setTick((n) => n + 1);
        onChange?.();
      }}
      className={`shrink-0 inline-flex items-center justify-center w-8 h-8 rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        isOn
          ? 'text-amber-300 hover:bg-amber-500/15'
          : 'text-on-surface-variant hover:bg-surface-container-high'
      }`}
    >
      <span className="material-symbols-outlined text-[20px]">
        {isOn ? 'star' : 'star_outline'}
      </span>
    </button>
  );
}
