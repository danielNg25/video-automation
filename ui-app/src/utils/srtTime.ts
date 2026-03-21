/** SRT timestamp parsing and formatting utilities. */

/** Convert SRT timestamp "HH:MM:SS,mmm" to seconds. */
export function srtTimestampToSeconds(ts: string): number {
  const match = ts.match(/^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})$/);
  if (!match) return 0;
  const [, h, m, s, ms] = match;
  return Number(h) * 3600 + Number(m) * 60 + Number(s) + Number(ms) / 1000;
}

/** Convert seconds to SRT timestamp "HH:MM:SS,mmm". */
export function secondsToSrtTimestamp(seconds: number): string {
  const clamped = Math.max(0, seconds);
  const h = Math.floor(clamped / 3600);
  const m = Math.floor((clamped % 3600) / 60);
  const s = Math.floor(clamped % 60);
  const ms = Math.round((clamped % 1) * 1000);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

/** Format seconds for display as "MM:SS.m" (compact). */
export function formatDisplayTime(seconds: number): string {
  const clamped = Math.max(0, seconds);
  const m = Math.floor(clamped / 60);
  const s = Math.floor(clamped % 60);
  const tenths = Math.floor((clamped % 1) * 10);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${tenths}`;
}

/** Validate SRT timestamp format. */
export function isValidSrtTimestamp(ts: string): boolean {
  return /^\d{2}:\d{2}:\d{2}[,.]?\d{3}$/.test(ts);
}
