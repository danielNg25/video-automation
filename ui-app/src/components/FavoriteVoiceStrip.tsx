import type { FavoriteVoice } from '../utils/favoriteVoices';
import type { VoiceInfo } from '../api/types';

interface Props {
  /** Already filtered to the current (provider, language) scope. */
  favorites: FavoriteVoice[];
  /** Currently-loaded voice metadata — used to render friendly_name when no nickname is set. */
  voices: VoiceInfo[];
  /** For highlighting the chip that matches what's currently picked. */
  selectedVoiceId: string;
  onPick: (voiceId: string) => void;
  onRemove: (fav: FavoriteVoice) => void;
  onRename: (fav: FavoriteVoice, nickname: string) => void;
}

function labelFor(fav: FavoriteVoice, voices: VoiceInfo[]): string {
  if (fav.nickname && fav.nickname.length > 0) return fav.nickname;
  const match = voices.find((v) => v.name === fav.voice);
  if (match?.friendly_name) return match.friendly_name;
  return fav.voice;
}

export function FavoriteVoiceStrip({
  favorites,
  voices,
  selectedVoiceId,
  onPick,
  onRemove,
  onRename,
}: Props) {
  if (favorites.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="text-[10px] font-bold uppercase tracking-tighter text-zinc-500 mr-1">
        ★ Favorites
      </span>
      {favorites.map((fav) => {
        const isSelected = fav.voice === selectedVoiceId;
        const label = labelFor(fav, voices);
        return (
          <span
            key={`${fav.provider}|${fav.voice}|${fav.language}`}
            className={`group inline-flex items-center gap-0.5 rounded-full pl-2.5 pr-1 py-1 text-[11px] font-medium border ${
              isSelected
                ? 'bg-primary/15 text-primary border-primary/30'
                : 'bg-surface-container-high text-on-surface border-outline-variant/20 hover:bg-surface-container-highest'
            }`}
            title={`${fav.provider} · ${fav.voice}`}
          >
            <button
              type="button"
              onClick={() => onPick(fav.voice)}
              aria-label={`Pick ${fav.voice}`}
              className={`truncate max-w-[160px] text-left bg-transparent border-none focus:outline-none cursor-pointer ${
                isSelected ? 'bg-primary/15 text-primary' : ''
              }`}
            >
              {label}
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                const next = window.prompt(
                  'Nickname (leave blank to clear)',
                  fav.nickname ?? '',
                );
                if (next === null) return; // cancel
                onRename(fav, next.trim());
              }}
              aria-label={`Rename ${fav.voice}`}
              className="opacity-0 group-hover:opacity-100 ml-0.5 w-5 h-5 inline-flex items-center justify-center rounded-full hover:bg-primary/15 text-on-surface-variant"
            >
              <span className="material-symbols-outlined text-[14px]">edit</span>
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onRemove(fav);
              }}
              aria-label={`Remove ${fav.voice}`}
              className="opacity-0 group-hover:opacity-100 w-5 h-5 inline-flex items-center justify-center rounded-full hover:bg-red-500/20 text-on-surface-variant hover:text-red-400"
            >
              <span className="material-symbols-outlined text-[14px]">close</span>
            </button>
          </span>
        );
      })}
    </div>
  );
}
