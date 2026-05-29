import { useState } from 'react';
import type { VersionEntry } from '../../api/types';

interface VersionPanelProps {
  versions: VersionEntry[];
  onRename: (versionId: string, name: string | null) => void;
  onDelete: (versionId: string) => void;
}

export function VersionPanel({ versions, onRename, onDelete }: VersionPanelProps) {
  const [editingId, setEditingId] = useState<string | null>(null);

  if (versions.length === 0) {
    return null;
  }

  return (
    <div className="pt-3 mt-3 border-t border-outline-variant/10">
      <div className="text-[10px] uppercase tracking-wider text-on-surface-variant mb-2">
        Saved versions
      </div>
      <div className="flex flex-col gap-1">
        {versions.map((v) => (
          <div
            key={v.id}
            className="flex items-center gap-2 px-2 py-1.5 rounded bg-surface-container-lowest"
          >
            <span className="text-[10px] font-mono font-semibold text-primary bg-primary/15 px-1.5 py-0.5 rounded">
              {v.id}
            </span>
            {editingId === v.id ? (
              <input
                autoFocus
                defaultValue={v.name ?? ''}
                onBlur={(e) => {
                  setEditingId(null);
                  const next = e.target.value.trim();
                  onRename(v.id, next === '' ? null : next);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === 'Escape') {
                    (e.target as HTMLInputElement).blur();
                  }
                }}
                className="flex-1 bg-transparent text-xs text-on-surface border-b border-primary/40 focus:outline-none"
              />
            ) : (
              <span
                onClick={() => setEditingId(v.id)}
                className="flex-1 text-xs text-on-surface cursor-text hover:bg-primary/5 px-1 rounded"
              >
                {v.name ?? '(no name)'}
              </span>
            )}
            <button
              onClick={() => onDelete(v.id)}
              title="Delete version"
              className="p-1 rounded text-on-surface-variant hover:text-red-400 hover:bg-red-500/10"
            >
              <span className="material-symbols-outlined text-[14px]">delete</span>
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
