import type { VersionEntry } from '../../api/types';

interface VersionPickerProps {
  versions: VersionEntry[];
  /** The selected version id: 'draft' or one of the entries' ids. */
  value: string;
  onChange: (next: string) => void;
}

export function VersionPicker({ versions, value, onChange }: VersionPickerProps) {
  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 px-3 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-wider text-on-surface-variant">
          Subtitle version
        </span>
        <span className="text-[9px] text-on-surface-variant">
          edited in Editor tab
        </span>
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface border border-outline-variant/20 rounded px-2 py-1.5 text-xs text-on-surface focus:border-primary focus:outline-none"
      >
        <option value="draft">📝 Working Draft (latest edits)</option>
        {versions.map((v) => (
          <option key={v.id} value={v.id}>
            📌 {v.id} — {v.name ?? '(no name)'}
          </option>
        ))}
      </select>
    </div>
  );
}
