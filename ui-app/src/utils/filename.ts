/**
 * Filesystem-safe basename derived from `name`. Mirrors the BE's
 * `src/utils/filename.py::safe_filename` so the FE-side `<a download>`
 * suggestion agrees with the BE's `Content-Disposition` header.
 *
 * Returns the `fallback` (typically `videoId`) when the input is empty
 * or collapses to nothing after sanitisation.
 */
export function safeFilename(name: string | null | undefined, fallback: string): string {
  if (!name) return fallback;
  // eslint-disable-next-line no-control-regex
  let cleaned = name.replace(/[\\/:*?"<>|\x00-\x1f]/g, ' ');
  cleaned = cleaned.replace(/\s+/g, ' ').trim();
  cleaned = cleaned.replace(/[. ]+$/g, '');
  if (!cleaned) return fallback;
  if (cleaned.length > 200) cleaned = cleaned.slice(0, 200).replace(/\s+$/g, '');
  return cleaned;
}
