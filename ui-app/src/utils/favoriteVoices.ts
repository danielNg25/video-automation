export interface FavoriteVoice {
  provider: string;
  voice: string;
  language: string;
  /** Optional user-defined display label; missing/empty → fall back to friendly_name or voice id. */
  nickname?: string;
}

type FavoriteIdentity = Pick<FavoriteVoice, 'provider' | 'voice' | 'language'>;

const STORAGE_KEY = 'tts_favorite_voices_v1';

function sameIdentity(a: FavoriteIdentity, b: FavoriteIdentity): boolean {
  return a.provider === b.provider && a.voice === b.voice && a.language === b.language;
}

export function loadFavorites(): FavoriteVoice[] {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === null) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const out: FavoriteVoice[] = [];
  for (const entry of parsed) {
    if (
      typeof entry !== 'object' ||
      entry === null ||
      typeof (entry as Record<string, unknown>).provider !== 'string' ||
      typeof (entry as Record<string, unknown>).voice !== 'string' ||
      typeof (entry as Record<string, unknown>).language !== 'string'
    ) {
      continue;
    }
    const e = entry as Record<string, unknown>;
    const nick = typeof e.nickname === 'string' ? e.nickname : undefined;
    out.push({
      provider: e.provider as string,
      voice: e.voice as string,
      language: e.language as string,
      ...(nick !== undefined ? { nickname: nick } : {}),
    });
  }
  return out;
}

export function saveFavorites(list: FavoriteVoice[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch (err) {
    // localStorage quota or disabled — non-critical preference; surface to console only.
    console.warn('[favoriteVoices] saveFavorites failed', err);
  }
}

export function isFavorite(fav: FavoriteIdentity): boolean {
  return loadFavorites().some((f) => sameIdentity(f, fav));
}

export function toggleFavorite(fav: FavoriteVoice): FavoriteVoice[] {
  const current = loadFavorites();
  const idx = current.findIndex((f) => sameIdentity(f, fav));
  let next: FavoriteVoice[];
  if (idx >= 0) {
    // Remove (drops any existing nickname; re-adding starts fresh).
    next = [...current.slice(0, idx), ...current.slice(idx + 1)];
  } else {
    // Append. The supplied nickname (often absent on the star toggle path) is kept.
    next = [...current, fav];
  }
  saveFavorites(next);
  return next;
}

export function renameFavorite(
  fav: FavoriteIdentity,
  nickname: string,
): FavoriteVoice[] {
  const current = loadFavorites();
  const trimmed = nickname.trim();
  const next = current.map((f) => {
    if (!sameIdentity(f, fav)) return f;
    if (trimmed === '') {
      const { nickname: _drop, ...rest } = f;
      return rest;
    }
    return { ...f, nickname: trimmed };
  });
  // If the identity wasn't present, current === next by reference — saving is harmless.
  saveFavorites(next);
  return next;
}

export function favoritesFor(provider: string, language: string): FavoriteVoice[] {
  return loadFavorites().filter(
    (f) => f.provider === provider && f.language === language,
  );
}
