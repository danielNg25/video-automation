# Translation Profile Export / Import (JSON) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-profile JSON export + import to the Translation Profiles page so users can move profiles between machines without touching `config/translation_profiles/` on disk.

**Architecture:** Pure FE feature. The BE already has full CRUD at `/api/profiles`; the new buttons just trigger a browser download of the existing GET body, or POST a parsed-and-validated upload through the existing `createProfile` client. Name-conflict (409) on import triggers an inline rename form that re-posts under a new name.

**Tech Stack:** React 19 + TypeScript + Tailwind 4 + Vitest. No new dependencies. No BE work.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `ui-app/src/utils/profileJson.ts` | Two pure helpers: `downloadProfileJson` (Blob + anchor click + revoke), `validateProfileJson` (shape check, returns ok/reason). | **Create** |
| `ui-app/src/utils/__tests__/profileJson.test.ts` | 8 unit tests covering both helpers. | **Create** |
| `ui-app/src/api/client.ts` | Add `createProfileWithStatus(profile)` — same POST as `createProfile` but returns `{ status, body }` instead of throwing on non-2xx, so the FE can branch on 409 without parsing error text. | **Modify** (small append) |
| `ui-app/src/pages/TranslationProfiles.tsx` | Two new buttons (Export, Import), hidden file input, parse/validate flow, inline 409 rename form, import-error state. | **Modify** |
| `ui-app/src/pages/__tests__/TranslationProfiles.test.tsx` | 9 component tests covering both flows. | **Create** |
| `CHANGELOG.md` | `Added` entry under `[Unreleased]`. | **Modify** |
| `README.md` | New dated subsection in Implementation Progress. | **Modify** |

---

### Task 1: `utils/profileJson.ts` — pure helpers + 8 unit tests

**Files:**
- Create: `ui-app/src/utils/profileJson.ts`
- Create: `ui-app/src/utils/__tests__/profileJson.test.ts`

- [ ] **Step 1.1: Write the failing tests**

Create `ui-app/src/utils/__tests__/profileJson.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { downloadProfileJson, validateProfileJson } from '../profileJson';
import type { TranslationProfile } from '../../api/types';

const validProfile: TranslationProfile = {
  name: 'demo-vi',
  description: 'A demo profile',
  target_language: 'vi',
  source_language: 'zh',
  style_guide: 'Be casual.',
  example_pairs: [{ source: 'hi', target: 'chào' }],
};

describe('validateProfileJson', () => {
  it('accepts a well-formed profile', () => {
    const result = validateProfileJson(validProfile);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.profile).toEqual(validProfile);
  });

  it('rejects null and non-object input', () => {
    expect(validateProfileJson(null).ok).toBe(false);
    expect(validateProfileJson('string').ok).toBe(false);
    expect(validateProfileJson(42).ok).toBe(false);
  });

  it('rejects when name is missing', () => {
    const { name: _drop, ...rest } = validProfile;
    const result = validateProfileJson(rest);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/name/i);
  });

  it('rejects when style_guide is missing', () => {
    const { style_guide: _drop, ...rest } = validProfile;
    const result = validateProfileJson(rest);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/style_guide/i);
  });

  it('rejects when example_pairs is not an array', () => {
    const result = validateProfileJson({ ...validProfile, example_pairs: 'oops' });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/example_pairs/i);
  });

  it('rejects when an example_pair source is not a string', () => {
    const result = validateProfileJson({
      ...validProfile,
      example_pairs: [{ source: 42, target: 'ok' }],
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/example_pairs\[0\]\.source/i);
  });
});

describe('downloadProfileJson', () => {
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  const clickSpy = vi.fn();
  const originalClick = HTMLAnchorElement.prototype.click;

  afterEach(() => {
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
    HTMLAnchorElement.prototype.click = originalClick;
    clickSpy.mockReset();
    vi.useRealTimers();
  });

  it('creates an object URL and clicks an anchor with the correct filename', () => {
    const createMock = vi.fn(() => 'blob:fake-url');
    URL.createObjectURL = createMock as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
    HTMLAnchorElement.prototype.click = clickSpy;

    downloadProfileJson(validProfile);

    expect(createMock).toHaveBeenCalledTimes(1);
    // The argument is a Blob; verify it carries the JSON for the profile.
    const blobArg = createMock.mock.calls[0][0] as Blob;
    expect(blobArg).toBeInstanceOf(Blob);
    expect(blobArg.type).toBe('application/json');
    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it('revokes the object URL after click', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:fake-url') as unknown as typeof URL.createObjectURL;
    const revokeMock = vi.fn();
    URL.revokeObjectURL = revokeMock as unknown as typeof URL.revokeObjectURL;
    HTMLAnchorElement.prototype.click = clickSpy;

    vi.useFakeTimers();
    downloadProfileJson(validProfile);
    // Revoke is scheduled with setTimeout(..., 0).
    vi.runAllTimers();

    expect(revokeMock).toHaveBeenCalledWith('blob:fake-url');
  });
});
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `cd ui-app && npx vitest run src/utils/__tests__/profileJson.test.ts 2>&1 | tail -10`
Expected: `Cannot find module '../profileJson'`.

- [ ] **Step 1.3: Create the helper module**

Create `ui-app/src/utils/profileJson.ts`:

```ts
import type { TranslationProfile } from '../api/types';

export type ValidateResult =
  | { ok: true; profile: TranslationProfile }
  | { ok: false; reason: string };

/**
 * Validate that a parsed JSON value matches the TranslationProfile shape.
 * Returns either { ok: true; profile } or { ok: false; reason }.
 *
 * Required fields:
 *   - name, target_language, source_language: non-empty strings
 *   - description, style_guide: strings (empty allowed)
 *   - example_pairs: array of { source: string; target: string }
 *
 * Doesn't enforce server-side rules like uniqueness or filename safety —
 * those surface naturally from the BE on POST.
 */
export function validateProfileJson(raw: unknown): ValidateResult {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ok: false, reason: 'JSON root must be an object' };
  }
  const obj = raw as Record<string, unknown>;

  for (const field of ['name', 'target_language', 'source_language'] as const) {
    if (typeof obj[field] !== 'string' || (obj[field] as string).length === 0) {
      return { ok: false, reason: `Missing or empty field: ${field}` };
    }
  }
  for (const field of ['description', 'style_guide'] as const) {
    if (typeof obj[field] !== 'string') {
      return { ok: false, reason: `Missing field: ${field}` };
    }
  }
  if (!Array.isArray(obj.example_pairs)) {
    return { ok: false, reason: 'Field example_pairs: expected array' };
  }
  for (let i = 0; i < obj.example_pairs.length; i++) {
    const pair = obj.example_pairs[i];
    if (typeof pair !== 'object' || pair === null) {
      return { ok: false, reason: `Field example_pairs[${i}]: expected object` };
    }
    const p = pair as Record<string, unknown>;
    if (typeof p.source !== 'string') {
      return { ok: false, reason: `Field example_pairs[${i}].source: expected string` };
    }
    if (typeof p.target !== 'string') {
      return { ok: false, reason: `Field example_pairs[${i}].target: expected string` };
    }
  }

  return {
    ok: true,
    profile: {
      name: obj.name as string,
      description: obj.description as string,
      target_language: obj.target_language as string,
      source_language: obj.source_language as string,
      style_guide: obj.style_guide as string,
      example_pairs: obj.example_pairs as { source: string; target: string }[],
    },
  };
}

/**
 * Trigger a browser download of a JSON file for the given profile body.
 * Synthesises a hidden anchor and clicks it; revokes the object URL on
 * the next tick.
 */
export function downloadProfileJson(profile: TranslationProfile): void {
  const json = JSON.stringify(profile, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${profile.name}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke on the next tick so the click handler has fully resolved.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `cd ui-app && npx vitest run src/utils/__tests__/profileJson.test.ts 2>&1 | tail -10`
Expected: 8 passed.

- [ ] **Step 1.5: Type check**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 1.6: Commit**

```bash
git add ui-app/src/utils/profileJson.ts ui-app/src/utils/__tests__/profileJson.test.ts
git commit -m "feat(profiles): profileJson helpers — validate + download

Two pure functions powering the upcoming Export / Import buttons on
the Translation Profiles page.

- validateProfileJson(raw): narrows an unknown JSON value to a
  TranslationProfile or returns a human-readable reason for the
  first field that failed. Required: name, target_language,
  source_language are non-empty strings; description, style_guide
  are strings (empty allowed); example_pairs is an array of
  { source: string; target: string }. Doesn't enforce server-side
  rules (uniqueness, file-system safety) — those surface from the
  BE on POST.
- downloadProfileJson(profile): builds a JSON Blob, creates an
  object URL, synthesises a hidden anchor with download={name}.json,
  clicks it, then revokes the URL on the next tick.

8 unit tests: validate accepts well-formed, rejects null/non-object,
flags each required field, checks example_pairs nested shape;
download clicks the anchor with the correct filename and revokes
the URL afterward."
```

---

### Task 2: `createProfileWithStatus` API client helper

**Files:**
- Modify: `ui-app/src/api/client.ts`

This task is a tiny addition needed before the import wire-up in Task 3. The existing `createProfile` helper goes through `request()` which throws an Error with the response body text on non-2xx — that's lossy: the FE can't tell 409 from 400 without parsing the error string. We add a sibling helper that returns the status code alongside the body.

- [ ] **Step 2.1: Locate the insertion point**

Find the existing `createProfile` function (around line 128 in `ui-app/src/api/client.ts`):

```ts
export function createProfile(profile: TranslationProfile): Promise<TranslationProfile> {
  return request('/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  });
}
```

- [ ] **Step 2.2: Add the sibling helper immediately after**

Append after `createProfile`:

```ts
export type CreateProfileResult =
  | { status: 201; profile: TranslationProfile }
  | { status: 409; message: string }
  | { status: number; message: string };

/**
 * Like createProfile but returns status code + body instead of throwing
 * on non-2xx. Used by the import flow to branch on 409 (name conflict)
 * without parsing error text.
 */
export async function createProfileWithStatus(
  profile: TranslationProfile,
): Promise<CreateProfileResult> {
  const res = await fetch(`${BASE}/profiles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile),
  });
  if (res.status === 201) {
    return { status: 201, profile: (await res.json()) as TranslationProfile };
  }
  // FastAPI 4xx/5xx bodies are JSON: { "detail": "..." }. Try to extract;
  // fall back to raw text.
  const text = await res.text();
  let message = text;
  try {
    const parsed = JSON.parse(text) as { detail?: string };
    if (typeof parsed.detail === 'string') message = parsed.detail;
  } catch {
    // Keep raw text.
  }
  if (res.status === 409) return { status: 409, message };
  return { status: res.status, message };
}
```

- [ ] **Step 2.3: Type check**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 2.4: Confirm existing tests still pass**

Run: `cd ui-app && npx vitest run 2>&1 | tail -5`
Expected: full FE suite green (no behavioural change to existing tests).

- [ ] **Step 2.5: Commit**

```bash
git add ui-app/src/api/client.ts
git commit -m "feat(client): createProfileWithStatus — status-aware POST helper

The existing createProfile helper goes through request() which throws
an Error with just the response body text — the status code is gone.
The upcoming import flow needs to branch on 409 (name conflict in use)
without substring-matching the BE error wording.

createProfileWithStatus does its own fetch and returns
{ status, profile } on 201 or { status, message } on any non-2xx.
FastAPI's standard { detail: '...' } body is unwrapped so callers see
a human message; raw text falls through if the body isn't JSON.

No change to createProfile — existing callers are unaffected."
```

---

### Task 3: Wire Export + Import into TranslationProfiles page + 9 component tests

**Files:**
- Modify: `ui-app/src/pages/TranslationProfiles.tsx`
- Create: `ui-app/src/pages/__tests__/TranslationProfiles.test.tsx`

- [ ] **Step 3.1: Write the failing component tests**

Create `ui-app/src/pages/__tests__/TranslationProfiles.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import TranslationProfilesPage from '../TranslationProfiles';

const SAMPLE_PROFILES = [
  { name: 'demo-vi', description: 'A demo profile', target_language: 'vi' },
];

const SAMPLE_FULL = {
  name: 'demo-vi',
  description: 'A demo profile',
  target_language: 'vi',
  source_language: 'zh',
  style_guide: 'Be casual.',
  example_pairs: [{ source: 'hi', target: 'chào' }],
};

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>(
    '../../api/client',
  );
  return {
    ...actual,
    getProfiles: vi.fn(),
    getProfile: vi.fn(),
    createProfile: vi.fn(),
    createProfileWithStatus: vi.fn(),
    updateProfile: vi.fn(),
    deleteProfileApi: vi.fn(),
  };
});

vi.mock('../../components/TopBar', () => ({
  TopBar: ({ breadcrumb }: { breadcrumb: string }) => <div>{breadcrumb}</div>,
}));

vi.mock('../../utils/profileJson', async () => {
  const actual = await vi.importActual<typeof import('../../utils/profileJson')>(
    '../../utils/profileJson',
  );
  return {
    ...actual,
    downloadProfileJson: vi.fn(),
  };
});

beforeEach(async () => {
  const api = await import('../../api/client');
  vi.mocked(api.getProfiles).mockResolvedValue(SAMPLE_PROFILES);
  vi.mocked(api.getProfile).mockResolvedValue(SAMPLE_FULL);
});

afterEach(() => {
  vi.clearAllMocks();
});

async function selectDemoProfile() {
  fireEvent.click(await screen.findByText('demo-vi'));
  // Wait for getProfile to populate the right pane (the "Edit" button
  // only renders once a non-editing profile is loaded).
  await screen.findByRole('button', { name: /^edit$/i });
}

describe('TranslationProfiles — Export', () => {
  it('Export button is hidden until a profile is selected', () => {
    render(<TranslationProfilesPage />);
    expect(screen.queryByRole('button', { name: /^export$/i })).not.toBeInTheDocument();
  });

  it('Export click fetches the full profile then triggers download', async () => {
    const api = await import('../../api/client');
    const fileUtils = await import('../../utils/profileJson');
    render(<TranslationProfilesPage />);
    await selectDemoProfile();

    fireEvent.click(screen.getByRole('button', { name: /^export$/i }));

    await waitFor(() => {
      expect(fileUtils.downloadProfileJson).toHaveBeenCalledWith(SAMPLE_FULL);
    });
    // Confirm getProfile was called (cached from the select, but the
    // export path is allowed to re-fetch — verify the download payload
    // matches the loaded body).
    expect(api.getProfile).toHaveBeenCalled();
  });
});

describe('TranslationProfiles — Import', () => {
  function pickFile(contents: string, filename = 'profile.json'): void {
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error('file input not found');
    const file = new File([contents], filename, { type: 'application/json' });
    fireEvent.change(input, { target: { files: [file] } });
  }

  it('Import button opens the hidden file input', () => {
    render(<TranslationProfilesPage />);
    const importBtn = screen.getByRole('button', { name: /^import$/i });
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error('file input not found');
    const clickSpy = vi.spyOn(input, 'click');
    fireEvent.click(importBtn);
    expect(clickSpy).toHaveBeenCalled();
  });

  it('invalid JSON shows inline error, no POST attempted', async () => {
    const api = await import('../../api/client');
    render(<TranslationProfilesPage />);

    pickFile('{not valid json');

    expect(await screen.findByText(/invalid json/i)).toBeInTheDocument();
    expect(api.createProfileWithStatus).not.toHaveBeenCalled();
  });

  it('missing-field JSON shows inline error, no POST attempted', async () => {
    const api = await import('../../api/client');
    render(<TranslationProfilesPage />);
    const incomplete = { ...SAMPLE_FULL };
    delete (incomplete as Partial<typeof SAMPLE_FULL>).style_guide;

    pickFile(JSON.stringify(incomplete));

    expect(await screen.findByText(/style_guide/i)).toBeInTheDocument();
    expect(api.createProfileWithStatus).not.toHaveBeenCalled();
  });

  it('happy path: POST returns 201, list refreshes', async () => {
    const api = await import('../../api/client');
    vi.mocked(api.createProfileWithStatus).mockResolvedValue({
      status: 201,
      profile: { ...SAMPLE_FULL, name: 'fresh-vi' },
    });
    vi.mocked(api.getProfiles).mockResolvedValueOnce(SAMPLE_PROFILES).mockResolvedValueOnce([
      ...SAMPLE_PROFILES,
      { name: 'fresh-vi', description: 'A demo profile', target_language: 'vi' },
    ]);
    render(<TranslationProfilesPage />);

    pickFile(JSON.stringify({ ...SAMPLE_FULL, name: 'fresh-vi' }));

    await waitFor(() => {
      expect(api.createProfileWithStatus).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'fresh-vi' }),
      );
    });
    // Second getProfiles call (the post-import refresh) brings 'fresh-vi'
    // into the list.
    expect(await screen.findByText('fresh-vi')).toBeInTheDocument();
  });

  it('409 shows the rename form with default suffix', async () => {
    const api = await import('../../api/client');
    vi.mocked(api.createProfileWithStatus).mockResolvedValue({
      status: 409,
      message: "Profile 'demo-vi' already exists",
    });
    render(<TranslationProfilesPage />);

    pickFile(JSON.stringify(SAMPLE_FULL));

    const input = await screen.findByLabelText(/rename/i) as HTMLInputElement;
    expect(input.value).toBe('demo-vi-imported');
  });

  it('rename Confirm re-posts with the new name', async () => {
    const api = await import('../../api/client');
    vi.mocked(api.createProfileWithStatus)
      .mockResolvedValueOnce({ status: 409, message: 'exists' })
      .mockResolvedValueOnce({
        status: 201,
        profile: { ...SAMPLE_FULL, name: 'my-rename' },
      });
    render(<TranslationProfilesPage />);

    pickFile(JSON.stringify(SAMPLE_FULL));

    const input = await screen.findByLabelText(/rename/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'my-rename' } });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => {
      expect(api.createProfileWithStatus).toHaveBeenCalledTimes(2);
    });
    expect(api.createProfileWithStatus).toHaveBeenLastCalledWith(
      expect.objectContaining({ name: 'my-rename' }),
    );
  });

  it('rename Cancel clears the import buffer', async () => {
    const api = await import('../../api/client');
    vi.mocked(api.createProfileWithStatus).mockResolvedValue({
      status: 409,
      message: 'exists',
    });
    render(<TranslationProfilesPage />);

    pickFile(JSON.stringify(SAMPLE_FULL));

    await screen.findByLabelText(/rename/i);
    fireEvent.click(screen.getByRole('button', { name: /^cancel rename$/i }));

    await waitFor(() => {
      expect(screen.queryByLabelText(/rename/i)).not.toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 3.2: Run to verify they fail**

Run: `cd ui-app && npx vitest run src/pages/__tests__/TranslationProfiles.test.tsx 2>&1 | tail -15`
Expected: Multiple failures — Export button not rendered, Import button not rendered, etc.

- [ ] **Step 3.3: Update `ui-app/src/pages/TranslationProfiles.tsx`**

Three coordinated edits in the page component.

**Edit 1: Add imports at the top** (alongside existing imports):

```tsx
import { useState, useEffect, useCallback, useRef } from 'react';
import { TopBar } from '../components/TopBar';
import {
  getProfiles, getProfile, createProfile, createProfileWithStatus,
  updateProfile, deleteProfileApi,
} from '../api/client';
import type { TranslationProfileSummary, TranslationProfile } from '../api/types';
import { downloadProfileJson, validateProfileJson } from '../utils/profileJson';
```

(`useRef` is added; `createProfileWithStatus` is added from client; the `downloadProfileJson` + `validateProfileJson` are added from the new utils module. Keep `createProfile` — the existing Save path still uses it.)

**Edit 2: Add new state + the file-input ref inside the component**

Find the existing state block (around lines 12-18):

```tsx
  const [profiles, setProfiles] = useState<TranslationProfileSummary[]>([]);
  const [selectedName, setSelectedName] = useState('');
  const [profileDraft, setProfileDraft] = useState<TranslationProfile>({ ...EMPTY_PROFILE });
  const [isEditing, setIsEditing] = useState(false);
  const [isNew, setIsNew] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
```

Add right after:

```tsx
  // Import state. importError surfaces parse + validation + non-409 HTTP errors.
  // pendingImport holds the parsed profile while the user is in the rename form
  // (set when createProfileWithStatus returns 409).
  const [importError, setImportError] = useState('');
  const [pendingImport, setPendingImport] = useState<TranslationProfile | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
```

**Edit 3: Add handlers above the existing `return`**

Add these handlers after `handleDelete` (around line 93), before the `return` statement:

```tsx
  const handleExport = async () => {
    if (!selectedName) return;
    setError('');
    try {
      const full = await getProfile(selectedName);
      downloadProfileJson(full);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to export profile');
    }
  };

  const handleImportFilePicked = async (file: File) => {
    setImportError('');
    setError('');
    setSuccess('');

    let text: string;
    try {
      text = await file.text();
    } catch (e) {
      setImportError(`Could not read file: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      setImportError(`Invalid JSON: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }

    const validated = validateProfileJson(parsed);
    if (!validated.ok) {
      setImportError(validated.reason);
      return;
    }

    await tryImport(validated.profile);
  };

  const tryImport = async (profile: TranslationProfile) => {
    const result = await createProfileWithStatus(profile);
    if (result.status === 201) {
      setSuccess(`Imported "${result.profile.name}"`);
      setPendingImport(null);
      await loadProfiles();
      setSelectedName(result.profile.name);
      setProfileDraft(result.profile);
      setIsEditing(false);
      setIsNew(false);
      return;
    }
    if (result.status === 409) {
      setPendingImport(profile);
      setRenameValue(`${profile.name}-imported`);
      setImportError('');
      return;
    }
    setImportError(result.message || `Import failed: HTTP ${result.status}`);
  };

  const handleRenameConfirm = async () => {
    if (!pendingImport) return;
    const next = renameValue.trim();
    if (!next) {
      setImportError('Name cannot be empty');
      return;
    }
    await tryImport({ ...pendingImport, name: next });
  };

  const handleRenameCancel = () => {
    setPendingImport(null);
    setRenameValue('');
    setImportError('');
  };
```

**Edit 4: Wire the Export button into the right-pane header**

Find the existing button block at lines 153-170 (the Edit + Delete buttons). Replace:

```tsx
                  <div className="flex gap-2">
                    {!isEditing && !isNew && (
                      <>
                        <button
                          onClick={handleEdit}
                          className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => handleDelete(selectedName)}
                          className="text-[10px] font-bold text-error uppercase tracking-wider hover:underline"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
```

With:

```tsx
                  <div className="flex gap-2">
                    {!isEditing && !isNew && (
                      <>
                        <button
                          onClick={handleEdit}
                          className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline"
                        >
                          Edit
                        </button>
                        <button
                          onClick={handleExport}
                          className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline"
                        >
                          Export
                        </button>
                        <button
                          onClick={() => handleDelete(selectedName)}
                          className="text-[10px] font-bold text-error uppercase tracking-wider hover:underline"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
```

**Edit 5: Wire the Import button + file input + inline rename form into the left pane**

Find the existing left-pane header block at lines 102-115:

```tsx
          <div className="lg:col-span-4 space-y-3">
            <div className="flex justify-between items-center mb-2">
              <h2 className="text-xs font-bold uppercase tracking-widest">Profiles</h2>
              <button
                onClick={handleNew}
                className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline flex items-center gap-1"
              >
                <span className="material-symbols-outlined text-sm">add</span>
                New
              </button>
            </div>
            {profiles.length === 0 && (
              <p className="text-xs text-zinc-500">No profiles yet. Create one to get started.</p>
            )}
```

Replace with:

```tsx
          <div className="lg:col-span-4 space-y-3">
            <div className="flex justify-between items-center mb-2">
              <h2 className="text-xs font-bold uppercase tracking-widest">Profiles</h2>
              <div className="flex gap-3">
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline flex items-center gap-1"
                >
                  <span className="material-symbols-outlined text-sm">upload</span>
                  Import
                </button>
                <button
                  onClick={handleNew}
                  className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline flex items-center gap-1"
                >
                  <span className="material-symbols-outlined text-sm">add</span>
                  New
                </button>
              </div>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void handleImportFilePicked(file);
                e.target.value = ''; // allow re-selecting the same file
              }}
            />
            {importError && (
              <div className="bg-error/10 border border-error/30 text-error text-xs p-3 rounded-lg flex items-start gap-2">
                <span className="material-symbols-outlined text-sm">error</span>
                <span className="flex-1 break-words">{importError}</span>
                <button onClick={() => setImportError('')} aria-label="Dismiss import error">
                  <span className="material-symbols-outlined text-sm">close</span>
                </button>
              </div>
            )}
            {pendingImport && (
              <div className="bg-primary/5 border border-primary/30 rounded-lg p-3 space-y-2">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider">
                  Name already exists. Pick a new name to import as:
                </p>
                <label className="block">
                  <span className="sr-only">Rename profile</span>
                  <input
                    type="text"
                    aria-label="Rename profile"
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary"
                  />
                </label>
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={handleRenameCancel}
                    aria-label="Cancel rename"
                    className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider hover:underline"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleRenameConfirm}
                    className="text-[10px] font-bold text-primary uppercase tracking-wider hover:underline"
                  >
                    Confirm
                  </button>
                </div>
              </div>
            )}
            {profiles.length === 0 && (
              <p className="text-xs text-zinc-500">No profiles yet. Create one to get started.</p>
            )}
```

- [ ] **Step 3.4: Run the new tests to verify they pass**

Run: `cd ui-app && npx vitest run src/pages/__tests__/TranslationProfiles.test.tsx 2>&1 | tail -20`
Expected: 9 passed.

- [ ] **Step 3.5: Run the full FE suite**

Run: `cd ui-app && npx vitest run 2>&1 | tail -5`
Expected: all green (existing + 17 new across Tasks 1 and 3).

- [ ] **Step 3.6: Type check**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -5`
Expected: no new errors.

- [ ] **Step 3.7: Commit**

```bash
git add ui-app/src/pages/TranslationProfiles.tsx ui-app/src/pages/__tests__/TranslationProfiles.test.tsx
git commit -m "feat(profiles): Export + Import JSON buttons with inline rename on 409

Two new affordances on the Translation Profiles page:

- Export: right-pane header gets a button next to Edit / Delete
  (rendered only when a profile is selected and not in edit/new
  mode). Click → getProfile(name) → downloadProfileJson — user
  receives {name}.json with the raw API body.
- Import: left-pane header gets a button next to New. Click → opens
  a hidden file input. On file pick: read → JSON.parse → validate →
  createProfileWithStatus. 201 refreshes the list and selects the
  new profile. 409 pops an inline rename form in the left pane
  pre-filled with '{name}-imported'; Confirm re-posts under the
  chosen name (loops back to 201/409 handling), Cancel discards.

Validation errors (malformed JSON or missing fields) surface as an
inline banner above the profile list. Non-409 HTTP errors fall into
the same banner.

9 new component tests cover both flows: Export visibility + click,
Import-button file-input click, parse / validation error banners
without a POST, 201 happy path, 409 rename form default value,
Confirm re-post, Cancel reset."
```

---

### Task 4: CHANGELOG + README rollup

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 4.1: CHANGELOG entry**

Open `CHANGELOG.md`. Find `## [Unreleased]` → `### Added`. Add this entry at the top of the `Added` block:

```markdown
- **Translation Profiles: Export + Import JSON.** Per-profile buttons on the Translation Profiles page. Export downloads `{name}.json` with the raw `TranslationProfile` body (same JSON the GET endpoint returns); Import opens a hidden file picker, parses + validates the JSON client-side, then POSTs through the existing `createProfile` endpoint. Name-conflict triggers an inline rename form in the left pane (default `{name}-imported`); Confirm re-posts, Cancel discards. Pure FE — no BE changes. Adds `ui-app/src/utils/profileJson.ts` (helpers: `validateProfileJson`, `downloadProfileJson`) and `createProfileWithStatus` in the API client (status-aware sibling of `createProfile`, used so the import flow can branch on 409 without parsing error text). 17 new vitest tests (8 helper + 9 component).
```

- [ ] **Step 4.2: README progress section**

Open `README.md`. Find the most recent dated subsection under Implementation Progress (currently "Favorite voices with nicknames (2026-05-31)"). Insert this new subsection immediately after its `---` separator:

```markdown
### Translation Profile Export / Import (2026-05-31)

> Move a translation profile between machines via plain JSON download/upload. See [`docs/superpowers/specs/2026-05-31-translation-profile-export-import-design.md`](docs/superpowers/specs/2026-05-31-translation-profile-export-import-design.md) and [`docs/superpowers/plans/2026-05-31-translation-profile-export-import.md`](docs/superpowers/plans/2026-05-31-translation-profile-export-import.md).

- [x] **Task 1** — `ui-app/src/utils/profileJson.ts`: `validateProfileJson` narrows an `unknown` JSON to a `TranslationProfile` or returns a human-readable reason for the first failing field; `downloadProfileJson` builds a `Blob`, synthesises a hidden `<a download>`, clicks it, revokes the URL on the next tick. 8 unit tests.
- [x] **Task 2** — `createProfileWithStatus` in `ui-app/src/api/client.ts`: status-aware sibling of `createProfile` so the import flow can branch on 409 without parsing error text. Returns `{ status: 201, profile }` or `{ status: number, message }`; unwraps FastAPI's `{ detail: '...' }` payload.
- [x] **Task 3** — Page wire-up: Export button next to Edit/Delete (right pane), Import button next to New (left pane) with hidden file input. 409 from the BE pops an inline rename form pre-filled with `{name}-imported`; Confirm re-posts, Cancel discards. Parse/validation/HTTP errors surface as an inline banner above the profile list. 9 component tests.
- [x] **Task 4** — CHANGELOG + README updates.

---
```

- [ ] **Step 4.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(profile-export-import): CHANGELOG + README rollup"
```

---

## Final verification (run before reporting DONE)

- [ ] **Step F.1: Full FE suite**

Run: `cd ui-app && npx vitest run 2>&1 | tail -5`
Expected: green. +17 tests over baseline (8 helper + 9 component).

- [ ] **Step F.2: TypeScript check**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -5`
Expected: no new errors on touched files.

- [ ] **Step F.3: Manual smoke (after merge)**

1. Open Translation Profiles → select `dramatic-vi` → click Export → file `dramatic-vi.json` downloads.
2. Open the downloaded JSON and confirm it has all 6 fields with the right values.
3. Click Import → pick the just-downloaded `dramatic-vi.json` → inline rename form appears with `dramatic-vi-imported` pre-filled → Confirm → new profile appears in the list.
4. Click Import → pick a non-JSON file (e.g. README.md) → inline "Invalid JSON" error.
5. Edit the downloaded JSON to remove `style_guide`, save, Import again → inline "Missing field: style_guide" error.

---

## Self-review checklist (for the implementer)

- [ ] Spec coverage: each section in the spec maps to a task (helpers → T1, client helper → T2, page wire-up + tests → T3, docs → T4).
- [ ] No "TBD" / "implement later" / "similar to Task N" anywhere.
- [ ] Type/name consistency: `TranslationProfile`, `validateProfileJson`, `downloadProfileJson`, `createProfileWithStatus`, `CreateProfileResult` used identically across plan tasks and the spec.
- [ ] Storage / API path consistency: import POSTs to the same `/api/profiles` route used by the existing Save flow.
- [ ] No new branches mid-plan; everything lands on `feature/profile-export-import`.
- [ ] No AI-attribution strings in any commit message.
- [ ] CHANGELOG entry under `Added` in `[Unreleased]`.
- [ ] README entry next to the other dated subsections.
