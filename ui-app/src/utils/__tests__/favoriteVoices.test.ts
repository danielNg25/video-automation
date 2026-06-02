import { afterEach, describe, expect, it } from 'vitest';
import {
  favoritesFor,
  isFavorite,
  loadFavorites,
  renameFavorite,
  saveFavorites,
  toggleFavorite,
} from '../favoriteVoices';

const KEY = 'tts_favorite_voices_v1';

afterEach(() => {
  localStorage.removeItem(KEY);
});

describe('favoriteVoices — load/save', () => {
  it('returns empty when the key is missing', () => {
    expect(loadFavorites()).toEqual([]);
  });

  it('returns empty on malformed JSON', () => {
    localStorage.setItem(KEY, '{not valid json');
    expect(loadFavorites()).toEqual([]);
  });

  it('filters entries missing any of provider/voice/language', () => {
    localStorage.setItem(
      KEY,
      JSON.stringify([
        { provider: 'google', voice: 'v1', language: 'vi' },
        { voice: 'v2', language: 'vi' },           // missing provider
        { provider: 'google', language: 'vi' },    // missing voice
        { provider: 'google', voice: 'v3' },       // missing language
        'not even an object',
      ]),
    );
    const out = loadFavorites();
    expect(out).toHaveLength(1);
    expect(out[0].voice).toBe('v1');
  });

  it('normalises invalid nickname to undefined', () => {
    localStorage.setItem(
      KEY,
      JSON.stringify([
        { provider: 'google', voice: 'v1', language: 'vi', nickname: 42 },
        { provider: 'google', voice: 'v2', language: 'vi', nickname: 'Sarah' },
        { provider: 'google', voice: 'v3', language: 'vi' },
      ]),
    );
    const out = loadFavorites();
    expect(out[0].nickname).toBeUndefined();
    expect(out[1].nickname).toBe('Sarah');
    expect(out[2].nickname).toBeUndefined();
  });
});

describe('favoriteVoices — identity ops', () => {
  it('isFavorite matches identity (provider, voice, language), ignoring nickname', () => {
    saveFavorites([
      { provider: 'google', voice: 'v1', language: 'vi', nickname: 'Sarah' },
    ]);
    expect(isFavorite({ provider: 'google', voice: 'v1', language: 'vi' })).toBe(true);
    // Different nickname doesn't matter — identity still matches. (isFavorite's
    // type is Pick<…> so an extra nickname field is structurally compatible.)
    expect(
      isFavorite({ provider: 'google', voice: 'v1', language: 'vi', nickname: 'Other' } as never),
    ).toBe(true);
    // Different language → no match.
    expect(isFavorite({ provider: 'google', voice: 'v1', language: 'en' })).toBe(false);
  });

  it('toggleFavorite adds when absent', () => {
    const out = toggleFavorite({ provider: 'google', voice: 'v1', language: 'vi' });
    expect(out).toHaveLength(1);
    expect(loadFavorites()).toHaveLength(1);
  });

  it('toggleFavorite removes when present', () => {
    saveFavorites([
      { provider: 'google', voice: 'v1', language: 'vi' },
      { provider: 'google', voice: 'v2', language: 'vi' },
    ]);
    const out = toggleFavorite({ provider: 'google', voice: 'v1', language: 'vi' });
    expect(out).toHaveLength(1);
    expect(out[0].voice).toBe('v2');
  });

  it('toggleFavorite drops the nickname on remove', () => {
    saveFavorites([
      { provider: 'google', voice: 'v1', language: 'vi', nickname: 'Sarah' },
    ]);
    // First toggle removes it.
    toggleFavorite({ provider: 'google', voice: 'v1', language: 'vi' });
    // Re-toggle adds it back — but without the nickname.
    const out = toggleFavorite({ provider: 'google', voice: 'v1', language: 'vi' });
    expect(out).toHaveLength(1);
    expect(out[0].nickname).toBeUndefined();
  });
});

describe('favoriteVoices — rename', () => {
  it('renameFavorite updates an existing entry', () => {
    saveFavorites([
      { provider: 'google', voice: 'v1', language: 'vi' },
    ]);
    const out = renameFavorite(
      { provider: 'google', voice: 'v1', language: 'vi' },
      'Sarah',
    );
    expect(out[0].nickname).toBe('Sarah');
    expect(loadFavorites()[0].nickname).toBe('Sarah');
  });

  it('renameFavorite clears the nickname when blank or whitespace', () => {
    saveFavorites([
      { provider: 'google', voice: 'v1', language: 'vi', nickname: 'Sarah' },
    ]);
    const out = renameFavorite(
      { provider: 'google', voice: 'v1', language: 'vi' },
      '   ',
    );
    expect(out[0].nickname).toBeUndefined();
  });

  it('renameFavorite is a no-op when the identity is not in the list', () => {
    saveFavorites([
      { provider: 'google', voice: 'v1', language: 'vi' },
    ]);
    const out = renameFavorite(
      { provider: 'google', voice: 'nonexistent', language: 'vi' },
      'x',
    );
    expect(out).toEqual(loadFavorites());
    expect(out[0].nickname).toBeUndefined();
  });
});

describe('favoriteVoices — favoritesFor scope filter', () => {
  it('filters by (provider, language) only', () => {
    saveFavorites([
      { provider: 'google', voice: 'a', language: 'vi' },
      { provider: 'google', voice: 'b', language: 'en' },
      { provider: 'elevenlabs', voice: 'c', language: 'vi' },
      { provider: 'google', voice: 'd', language: 'vi' },
    ]);
    const out = favoritesFor('google', 'vi');
    expect(out.map((f) => f.voice).sort()).toEqual(['a', 'd']);
  });
});
