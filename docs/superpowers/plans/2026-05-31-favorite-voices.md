# Favorite voices — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-browser favorites layer on top of the existing voice pickers — star a voice, click it later from a chip strip below the dropdown, optionally give it a personal nickname.

**Architecture:** One pure-helper module over a single localStorage key (`tts_favorite_voices_v1`), one strip component (renders the chips), one toggle component (the star button). Both pages (`DubStudio`, `DubTab`) wire the same components into their existing voice-picker JSX. Identity is `(provider, voice, language)`; `nickname` is optional display metadata.

**Tech Stack:** React 19 + TypeScript + Tailwind 4 + Vitest. No new dependencies. No BE work.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `ui-app/src/utils/favoriteVoices.ts` | Pure functions over the localStorage key. `loadFavorites`, `saveFavorites`, `isFavorite`, `toggleFavorite`, `renameFavorite`, `favoritesFor`. | **Create** |
| `ui-app/src/utils/__tests__/favoriteVoices.test.ts` | 12 unit tests covering load edge cases, identity-based ops, nickname normalisation, and scope filter. | **Create** |
| `ui-app/src/components/FavoriteVoiceStrip.tsx` | Renders the chip row. Each chip has body click (pick), hover-pencil (rename via `prompt`), hover-× (remove). Selected chip gets a tint. | **Create** |
| `ui-app/src/components/__tests__/FavoriteVoiceStrip.test.tsx` | 10 component tests covering empty state, three-tier label fallback (nickname → friendly → id), pick/remove/rename callbacks + event-stop, selected highlight. | **Create** |
| `ui-app/src/components/FavoriteVoiceToggle.tsx` | The star button. Filled vs outlined depending on `isFavorite`; click toggles + fires `onChange`. | **Create** |
| `ui-app/src/components/__tests__/FavoriteVoiceToggle.test.tsx` | 4 tests covering filled/outlined states, click toggle behavior, disabled state. | **Create** |
| `ui-app/src/pages/DubStudio.tsx` | Wire toggle inline with voice `<select>`; render strip below. | **Modify** |
| `ui-app/src/pages/__tests__/DubStudio.test.tsx` | 1 new integration test: strip renders when a matching favorite exists. | **Modify** |
| `ui-app/src/pages/videoDetail/DubTab.tsx` | Same wire-up (toggle inline with non-elevenlabs dropdown; strip below the voice section). | **Modify** |
| `ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx` | 1 new integration test: strip renders. | **Modify** |
| `CHANGELOG.md` | `Added` entry. | **Modify** |
| `README.md` | New dated sub-section in Implementation Progress. | **Modify** |

---

### Task 1: `utils/favoriteVoices.ts` — pure helpers + 12 unit tests

**Files:**
- Create: `ui-app/src/utils/favoriteVoices.ts`
- Create: `ui-app/src/utils/__tests__/favoriteVoices.test.ts`

- [ ] **Step 1.1: Write the failing tests**

Create `ui-app/src/utils/__tests__/favoriteVoices.test.ts`:

```ts
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
    // Different nickname doesn't matter — identity still matches.
    expect(isFavorite({ provider: 'google', voice: 'v1', language: 'vi' })).toBe(true);
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
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `cd ui-app && npx vitest run src/utils/__tests__/favoriteVoices.test.ts 2>&1 | tail -10`
Expected: `Cannot find module '../favoriteVoices'`.

- [ ] **Step 1.3: Create the helper module**

Create `ui-app/src/utils/favoriteVoices.ts`:

```ts
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
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `cd ui-app && npx vitest run src/utils/__tests__/favoriteVoices.test.ts 2>&1 | tail -10`
Expected: 12 passed.

- [ ] **Step 1.5: Lint clean**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 1.6: Commit**

```bash
git add ui-app/src/utils/favoriteVoices.ts ui-app/src/utils/__tests__/favoriteVoices.test.ts
git commit -m "feat(favorites): localStorage-backed favoriteVoices helpers

Pure functions over a single key 'tts_favorite_voices_v1' shared by
both the per-video DubTab and the standalone Dub Studio. A favorite
is identified by (provider, voice, language); 'nickname' is optional
display metadata.

- loadFavorites/saveFavorites: serialise via JSON, tolerate malformed
  payloads (returns [] on any failure), filter out entries missing any
  identity field, and normalise non-string nicknames to undefined.
- isFavorite: identity-based check, ignores nickname.
- toggleFavorite: identity-based add/remove. On remove, the nickname
  is dropped — re-toggling starts fresh.
- renameFavorite: updates nickname by identity; empty/whitespace
  clears back to undefined. No-op when the entry is absent.
- favoritesFor(provider, language): filter by the active page scope.

12 unit tests covering load edge cases, identity ops, rename paths,
and scope filter."
```

---

### Task 2: `FavoriteVoiceStrip.tsx` — chip row + 10 component tests

**Files:**
- Create: `ui-app/src/components/FavoriteVoiceStrip.tsx`
- Create: `ui-app/src/components/__tests__/FavoriteVoiceStrip.test.tsx`

- [ ] **Step 2.1: Write the failing tests**

Create `ui-app/src/components/__tests__/FavoriteVoiceStrip.test.tsx`:

```tsx
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
    vi.stubGlobal('prompt', vi.fn(() => '  Renamed  '));
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
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `cd ui-app && npx vitest run src/components/__tests__/FavoriteVoiceStrip.test.tsx 2>&1 | tail -10`
Expected: `Cannot find module '../FavoriteVoiceStrip'`.

- [ ] **Step 2.3: Create the strip component**

Create `ui-app/src/components/FavoriteVoiceStrip.tsx`:

```tsx
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
              className="truncate max-w-[160px] text-left bg-transparent border-none focus:outline-none cursor-pointer"
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
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `cd ui-app && npx vitest run src/components/__tests__/FavoriteVoiceStrip.test.tsx 2>&1 | tail -10`
Expected: 10 passed.

- [ ] **Step 2.5: Type check**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 2.6: Commit**

```bash
git add ui-app/src/components/FavoriteVoiceStrip.tsx ui-app/src/components/__tests__/FavoriteVoiceStrip.test.tsx
git commit -m "feat(favorites): FavoriteVoiceStrip chip row

A pill-chip strip rendered below the voice picker. Each chip:

- Body click → onPick(voice id). The chip's text follows a three-tier
  fallback: nickname → friendly_name (from the loaded voices list) →
  bare voice id. Tooltip always shows the full provider · voice
  identity so the user can see what's behind a nickname.
- Hover reveals a pencil and an × button. Pencil → window.prompt to
  set/clear the nickname; commit fires onRename with the trimmed
  value, cancel is a no-op. × → onRemove. Both icon handlers call
  event.stopPropagation so they don't also fire the body's onPick.
- Chip matching selectedVoiceId gets a bg-primary/15 text-primary
  highlight tint.
- Returns null when favorites is empty so the row carries no chrome
  at rest.

10 component tests covering empty state, label fallback chain,
pick/remove/rename callbacks, stopPropagation guard, and selected
highlight."
```

---

### Task 3: `FavoriteVoiceToggle.tsx` — star button + 4 component tests

**Files:**
- Create: `ui-app/src/components/FavoriteVoiceToggle.tsx`
- Create: `ui-app/src/components/__tests__/FavoriteVoiceToggle.test.tsx`

- [ ] **Step 3.1: Write the failing tests**

Create `ui-app/src/components/__tests__/FavoriteVoiceToggle.test.tsx`:

```tsx
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
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `cd ui-app && npx vitest run src/components/__tests__/FavoriteVoiceToggle.test.tsx 2>&1 | tail -10`
Expected: `Cannot find module '../FavoriteVoiceToggle'`.

- [ ] **Step 3.3: Create the toggle component**

Create `ui-app/src/components/FavoriteVoiceToggle.tsx`:

```tsx
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
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `cd ui-app && npx vitest run src/components/__tests__/FavoriteVoiceToggle.test.tsx 2>&1 | tail -10`
Expected: 4 passed.

- [ ] **Step 3.5: Type check**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 3.6: Commit**

```bash
git add ui-app/src/components/FavoriteVoiceToggle.tsx ui-app/src/components/__tests__/FavoriteVoiceToggle.test.tsx
git commit -m "feat(favorites): FavoriteVoiceToggle star button

The star button rendered next to the voice picker. Reads
isFavorite(provider, voice, language) on every render to decide
filled vs outlined; click calls toggleFavorite + fires the optional
onChange callback so the parent can re-load favorites and refresh
the strip.

Auto-disabled when voice is empty (e.g., voices still loading or the
provider needs an API key). The internal tick state forces a
re-read of localStorage on each click so the visual state flips
without the parent owning the bool.

4 component tests: outlined when not favorited, filled when
favorited, click writes to localStorage + fires onChange, disabled
when voice is empty."
```

---

### Task 4: Wire favorites into DubStudio + 1 integration test

**Files:**
- Modify: `ui-app/src/pages/DubStudio.tsx`
- Modify: `ui-app/src/pages/__tests__/DubStudio.test.tsx`

- [ ] **Step 4.1: Write the failing integration test**

Open `ui-app/src/pages/__tests__/DubStudio.test.tsx` and append a new test inside the existing `describe('DubStudio …')` block. If `loadFavorites`/`saveFavorites` aren't imported, add the import at the top:

```tsx
// add near the other imports at the top of the file:
import { saveFavorites } from '../../utils/favoriteVoices';
```

Add this test:

```tsx
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
    const api = await import('../../api/client');
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
    // Cleanup: drop the favorite so it doesn't leak into other tests.
    localStorage.removeItem('tts_favorite_voices_v1');
  });
```

- [ ] **Step 4.2: Run to verify it fails**

Run: `cd ui-app && npx vitest run src/pages/__tests__/DubStudio.test.tsx 2>&1 | tail -10`
Expected: the new test fails (Sarah text not found).

- [ ] **Step 4.3: Wire the components into DubStudio**

Open `ui-app/src/pages/DubStudio.tsx`. Three edits:

**Edit 1: Add imports at the top** (alongside the other imports — preserve existing order):

```tsx
import { FavoriteVoiceStrip } from '../components/FavoriteVoiceStrip';
import { FavoriteVoiceToggle } from '../components/FavoriteVoiceToggle';
import {
  favoritesFor,
  loadFavorites,
  renameFavorite,
  toggleFavorite,
} from '../utils/favoriteVoices';
import type { FavoriteVoice } from '../utils/favoriteVoices';
```

**Edit 2: Add favorites state inside the component** — find the existing `const [voices, setVoices] = useState<VoiceInfo[]>([]);` line (around line 70) and add right after it:

```tsx
  const [favorites, setFavorites] = useState<FavoriteVoice[]>(() => loadFavorites());
  // Re-derive the scoped view on every render — cheap (favorites list is <100 entries).
  const scopedFavorites = favorites.filter(
    (f) => f.provider === provider && f.language === language,
  );
```

The state owns the full list so the strip and the toggle stay in sync; the filter runs on every render but is trivially cheap.

**Edit 3: Update the voice section JSX.** Find the voice `<select>` block (around lines 383-405). The current shape is:

```tsx
          {/* Voice */}
          <div>
            <label className={labelClass}>Voice</label>
            {loadingVoices ? (
              <div className="…">Loading voices…</div>
            ) : (
              <select className={selectClass} value={voiceId} … >
                {/* options */}
              </select>
            )}
          </div>
```

Replace with:

```tsx
          {/* Voice */}
          <div>
            <label className={labelClass}>Voice</label>
            {loadingVoices ? (
              <div className="text-xs text-on-surface-variant italic px-3 py-2 bg-surface-container-highest border border-outline-variant/30 rounded">
                Loading voices…
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <select
                  className={selectClass}
                  value={voiceId}
                  onChange={(e) => handleSetVoiceId(e.target.value)}
                  disabled={voices.length === 0}
                >
                  {voices.length === 0 && <option value="">— no voices available —</option>}
                  {voices.map((v) => (
                    <option key={v.name} value={v.name}>
                      {v.friendly_name} ({v.gender})
                    </option>
                  ))}
                </select>
                <FavoriteVoiceToggle
                  provider={provider}
                  voice={voiceId}
                  language={language}
                  onChange={() => setFavorites(loadFavorites())}
                />
              </div>
            )}
            <FavoriteVoiceStrip
              favorites={scopedFavorites}
              voices={voices}
              selectedVoiceId={voiceId}
              onPick={(v) => handleSetVoiceId(v)}
              onRemove={(fav) => {
                toggleFavorite(fav);
                setFavorites(loadFavorites());
              }}
              onRename={(fav, nickname) => {
                renameFavorite(fav, nickname);
                setFavorites(loadFavorites());
              }}
            />
          </div>
```

- [ ] **Step 4.4: Run tests to verify everything passes**

Run: `cd ui-app && npx vitest run src/pages/__tests__/DubStudio.test.tsx 2>&1 | tail -10`
Expected: all green (existing + 1 new).

- [ ] **Step 4.5: Type check**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 4.6: Commit**

```bash
git add ui-app/src/pages/DubStudio.tsx ui-app/src/pages/__tests__/DubStudio.test.tsx
git commit -m "feat(dub-studio): favorites star button + chip strip

Wire FavoriteVoiceToggle inline with the voice <select> (same flex
row) and FavoriteVoiceStrip immediately below. Both share the same
state: a favorites list in the parent that re-reads from localStorage
every time the toggle, remove, or rename callback fires.

Scope is the current (provider, language) — chips filter to match,
re-render automatically when the picker switches scope.

The strip onPick wires straight into handleSetVoiceId so picking a
favorite is the same code path as picking from the dropdown.

One new vitest test confirms the strip renders when a matching
favorite is seeded in localStorage."
```

---

### Task 5: Wire favorites into DubTab + 1 integration test

**Files:**
- Modify: `ui-app/src/pages/videoDetail/DubTab.tsx`
- Modify: `ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx`

- [ ] **Step 5.1: Write the failing integration test**

Open `ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx` and add:

```tsx
// Add near the other imports if not already present:
import { saveFavorites } from '../../../utils/favoriteVoices';
```

Append a new describe block (or add to an existing one) at the end of the file:

```tsx
describe('DubTab — favorites strip', () => {
  afterEach(() => {
    localStorage.removeItem('tts_favorite_voices_v1');
  });

  it('renders the chip strip when a matching favorite exists', () => {
    saveFavorites([
      {
        provider: 'google',
        voice: 'vi-VN-Wavenet-A',
        language: 'vi',
        nickname: 'Sarah',
      },
    ]);
    renderDubTab({
      selectedTtsProvider: 'google',
      ttsLanguage: 'vi',
      ttsVoices: [
        {
          name: 'vi-VN-Wavenet-A',
          friendly_name: 'Vietnamese Wavenet A',
          gender: 'FEMALE',
          language: 'vi',
          provider: 'google',
        },
      ],
      selectedVoiceId: 'vi-VN-Wavenet-A',
    });
    expect(screen.getByText('Sarah')).toBeInTheDocument();
  });
});
```

If `afterEach` isn't imported at the top of the file yet, add it to the existing `import { ... } from 'vitest';` line.

- [ ] **Step 5.2: Run to verify it fails**

Run: `cd ui-app && npx vitest run src/pages/videoDetail/__tests__/DubTab.test.tsx 2>&1 | tail -10`
Expected: the new test fails (Sarah text not found).

- [ ] **Step 5.3: Wire the components into DubTab**

Open `ui-app/src/pages/videoDetail/DubTab.tsx`. Three edits:

**Edit 1: Add imports at the top** (alongside existing imports):

```tsx
import { FavoriteVoiceStrip } from '../../components/FavoriteVoiceStrip';
import { FavoriteVoiceToggle } from '../../components/FavoriteVoiceToggle';
import {
  favoritesFor,
  loadFavorites,
  renameFavorite,
  toggleFavorite,
} from '../../utils/favoriteVoices';
import type { FavoriteVoice } from '../../utils/favoriteVoices';
```

**Edit 2: Add favorites state inside the component.** Find the `useState`/`useNavigate` section near the top (around line 73-76 — `const [playingFilename, setPlayingFilename] = useState<string | null>(null);` etc.) and add:

```tsx
  const [favorites, setFavorites] = useState<FavoriteVoice[]>(() => loadFavorites());
  const scopedFavorites = favorites.filter(
    (f) => f.provider === selectedTtsProvider && f.language === ttsLanguage,
  );
```

If `useState` isn't already imported, ensure the top import line covers it.

**Edit 3: Update the voice picker JSX.** Find the `{/* Other providers: voice dropdown */}` block (around lines 183-204). Replace:

```tsx
      {/* Other providers: voice dropdown */}
      {selectedTtsProvider !== 'elevenlabs' && (
        <div className="space-y-1">
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block">Voice</label>
          <select
            value={selectedVoiceId}
            onChange={(e) => {
              const v = e.target.value;
              onChangeSelectedVoiceId(v);
              storageSet(`tts_voice_id_${selectedTtsProvider}`, v);
            }}
            className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
          >
            {ttsVoices.length === 0 && <option value="">Loading voices...</option>}
            {ttsVoices.map((v) => (
              <option key={v.name} value={v.name}>
                {v.friendly_name || v.name} ({v.gender}) — {v.language}
              </option>
            ))}
          </select>
        </div>
      )}
```

With:

```tsx
      {/* Other providers: voice dropdown + favorites strip */}
      {selectedTtsProvider !== 'elevenlabs' && (
        <div className="space-y-1">
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter block">Voice</label>
          <div className="flex items-center gap-2">
            <select
              value={selectedVoiceId}
              onChange={(e) => {
                const v = e.target.value;
                onChangeSelectedVoiceId(v);
                storageSet(`tts_voice_id_${selectedTtsProvider}`, v);
              }}
              className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-0"
            >
              {ttsVoices.length === 0 && <option value="">Loading voices...</option>}
              {ttsVoices.map((v) => (
                <option key={v.name} value={v.name}>
                  {v.friendly_name || v.name} ({v.gender}) — {v.language}
                </option>
              ))}
            </select>
            <FavoriteVoiceToggle
              provider={selectedTtsProvider}
              voice={selectedVoiceId}
              language={ttsLanguage}
              onChange={() => setFavorites(loadFavorites())}
            />
          </div>
          <FavoriteVoiceStrip
            favorites={scopedFavorites}
            voices={ttsVoices}
            selectedVoiceId={selectedVoiceId}
            onPick={(v) => {
              onChangeSelectedVoiceId(v);
              storageSet(`tts_voice_id_${selectedTtsProvider}`, v);
            }}
            onRemove={(fav) => {
              toggleFavorite(fav);
              setFavorites(loadFavorites());
            }}
            onRename={(fav, nickname) => {
              renameFavorite(fav, nickname);
              setFavorites(loadFavorites());
            }}
          />
        </div>
      )}
```

- [ ] **Step 5.4: Run tests to verify everything passes**

Run: `cd ui-app && npx vitest run src/pages/videoDetail/__tests__/DubTab.test.tsx 2>&1 | tail -10`
Expected: all green.

- [ ] **Step 5.5: Type check**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 5.6: Full FE suite**

Run: `cd ui-app && npx vitest run 2>&1 | tail -5`
Expected: all green.

- [ ] **Step 5.7: Commit**

```bash
git add ui-app/src/pages/videoDetail/DubTab.tsx ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx
git commit -m "feat(dub-tab): favorites star button + chip strip

Wire FavoriteVoiceToggle inline with the voice <select> (same flex
row) and FavoriteVoiceStrip immediately below. Lives inside the
non-elevenlabs branch only — elevenlabs uses a paste-voice-id flow,
and adding the favorites UI there is a separate scope (the toggle
already operates on any selected voice in DubStudio).

State + callback wiring mirrors DubStudio exactly: a favorites list
in the component, re-read from localStorage every time the toggle,
remove, or rename fires.

One new vitest test confirms the strip renders when a matching
favorite is seeded in localStorage."
```

---

### Task 6: CHANGELOG + README rollup

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 6.1: CHANGELOG entry**

Open `CHANGELOG.md`. Find `## [Unreleased]` → `### Added`. Add this entry at the top of the `Added` block:

```markdown
- **Favorite voices with custom nicknames.** Star a voice in either the per-video DubTab or the standalone Dub Studio to add it to a per-browser favorites list shared across both pages. Favorites surface as a chip strip immediately under the voice dropdown, filtered to the current (provider, language). Click a chip to pick that voice (same code path as the dropdown's onChange). Hover a chip to reveal a ✎ pencil (opens `window.prompt` to set/clear a nickname) and a × (remove). Chip text precedence: nickname → friendly_name → bare voice id; tooltip always shows the full `{provider} · {voice}` identity. Implementation: one `ui-app/src/utils/favoriteVoices.ts` helper module over localStorage key `tts_favorite_voices_v1`, two reusable components (`FavoriteVoiceStrip`, `FavoriteVoiceToggle`), wired identically into both pages. No BE work. 26 new vitest tests (12 helper + 10 strip + 4 toggle + 2 integration).
```

- [ ] **Step 6.2: README progress section**

Open `README.md`. Find the most recent dated subsection under Implementation Progress (currently "Auto-save shortened-dub SRT (2026-05-31)"). Insert this new subsection immediately after its `---` separator:

```markdown
### Favorite voices with nicknames (2026-05-31)

> Quick-select chips for the user's preferred TTS voices, with optional user-defined nicknames. See [`docs/superpowers/specs/2026-05-31-favorite-voices-design.md`](docs/superpowers/specs/2026-05-31-favorite-voices-design.md) and [`docs/superpowers/plans/2026-05-31-favorite-voices.md`](docs/superpowers/plans/2026-05-31-favorite-voices.md).

- [x] **Task 1** — `ui-app/src/utils/favoriteVoices.ts`: `loadFavorites`, `saveFavorites`, `isFavorite`, `toggleFavorite`, `renameFavorite`, `favoritesFor`. Identity is `(provider, voice, language)`; nickname is optional metadata. 12 unit tests covering load edge cases, identity ops, rename, and scope filter.
- [x] **Task 2** — `ui-app/src/components/FavoriteVoiceStrip.tsx`: pill-chip row with body-click pick, hover-pencil rename (via `window.prompt`), hover-× remove. Three-tier label fallback (nickname → friendly_name → voice id). 10 component tests.
- [x] **Task 3** — `ui-app/src/components/FavoriteVoiceToggle.tsx`: star button rendered next to the voice picker. Filled vs outlined per `isFavorite`; click toggles + fires optional `onChange`. 4 component tests.
- [x] **Task 4** — Wire into Dub Studio: toggle inline with voice select, strip below. 1 new integration test.
- [x] **Task 5** — Wire into DubTab (non-elevenlabs branch): same wire-up. 1 new integration test.
- [x] **Task 6** — CHANGELOG + README updates.

---
```

- [ ] **Step 6.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(favorite-voices): CHANGELOG + README rollup"
```

---

## Final verification (run before reporting DONE)

- [ ] **Step F.1: Full FE suite**

Run: `cd ui-app && npx vitest run 2>&1 | tail -5`
Expected: green. +26 tests over baseline.

- [ ] **Step F.2: TypeScript check**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -5`
Expected: no new errors on touched files.

- [ ] **Step F.3: Manual smoke (after merge)**

1. Open Dub Studio. Pick a voice. Click the star next to the dropdown → chip appears below.
2. Hover the chip. Click ✎. In the prompt, type "Sarah" and OK → chip relabels to "Sarah". Tooltip still shows the full provider · voice identity.
3. Hover ✎ again, submit empty → chip falls back to the friendly name.
4. Pick a different voice from the dropdown; click the original chip → dropdown jumps back, chip gets the highlight tint.
5. Hover ×; chip disappears.
6. Switch language to one with no matching favorites; strip hides.
7. Open a per-video editor → DubTab → the same favorites (with nicknames) are visible.

---

## Self-review checklist (for the implementer)

- [ ] Spec coverage: every section of the spec maps to a task — helper module (T1), strip + toggle (T2, T3), wire-ups (T4, T5), docs (T6).
- [ ] No "TBD" / "implement later" / "similar to Task N" anywhere.
- [ ] Type / name consistency: `FavoriteVoice`, `loadFavorites`, `toggleFavorite`, `renameFavorite`, `favoritesFor`, `FavoriteVoiceStrip`, `FavoriteVoiceToggle` used identically across plan tasks and the spec.
- [ ] Storage key `tts_favorite_voices_v1` matches in the helper module and the tests.
- [ ] Snapshot of behavior in `toggleFavorite` (remove drops nickname; re-add starts fresh) consistently tested in helper tests and reflected in the spec table.
- [ ] No new branches created mid-plan; all work lands on `feature/favorite-voices`.
- [ ] No AI-attribution strings in any commit message.
- [ ] CHANGELOG entry under `Added` in `[Unreleased]`.
- [ ] README entry next to other dated implementation-progress subsections, not at the bottom.
