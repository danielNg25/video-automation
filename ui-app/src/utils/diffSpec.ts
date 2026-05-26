import type { SubtitleStyleSpec, SubtitleStyleDelta } from '../api/types';

/** Returns only the fields where `draft` differs from `global`. Drops empty groups. */
export function diffSpec(draft: SubtitleStyleSpec, global: SubtitleStyleSpec): SubtitleStyleDelta {
  const delta: SubtitleStyleDelta = {};
  for (const group of Object.keys(draft) as (keyof SubtitleStyleSpec)[]) {
    const draftGroup = draft[group] as unknown as Record<string, unknown>;
    const globalGroup = global[group] as unknown as Record<string, unknown>;
    const changed: Record<string, unknown> = {};
    for (const key of Object.keys(draftGroup)) {
      if (draftGroup[key] !== globalGroup[key]) changed[key] = draftGroup[key];
    }
    if (Object.keys(changed).length > 0) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (delta as any)[group] = changed;
    }
  }
  return delta;
}
