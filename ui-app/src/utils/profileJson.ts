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
