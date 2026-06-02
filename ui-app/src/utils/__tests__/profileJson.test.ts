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
