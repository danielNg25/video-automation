/**
 * Persisted user-added Vbee voice codes.
 *
 * Vbee has no public voice-list endpoint, so the dropdown ships a small
 * curated set. Users can paste any voiceCode from their Vbee dashboard and
 * "Add" it — those codes live here in localStorage and get merged into the
 * voice dropdown so they're selectable everywhere (preview + generate),
 * surviving reloads.
 */

const KEY = 'vbee_custom_voices';

export function loadCustomVbeeVoices(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

/** Append a code (trimmed, deduped). Returns the new list. No-op for empty. */
export function addCustomVbeeVoice(code: string): string[] {
  const c = code.trim();
  const list = loadCustomVbeeVoices();
  if (!c || list.includes(c)) return list;
  const next = [...list, c];
  localStorage.setItem(KEY, JSON.stringify(next));
  return next;
}

/** Remove a code. Returns the new list. */
export function removeCustomVbeeVoice(code: string): string[] {
  const next = loadCustomVbeeVoices().filter((c) => c !== code);
  localStorage.setItem(KEY, JSON.stringify(next));
  return next;
}
