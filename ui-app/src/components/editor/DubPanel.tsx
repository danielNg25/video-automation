import type { TTSAudioEntry } from '../../api/client';

interface DubPanelProps {
  /** Dubs already filtered by the editor's active language. */
  dubs: TTSAudioEntry[];
  /** Builds the download href for a dub. Returning null/empty skips
   *  rendering the button (defensive — never expected in practice). */
  buildDownloadUrl: (filename: string) => string | null;
}

/** Lists generated dubs (one per row) with a download icon — mirrors
 *  the VersionPanel layout below the segment list. */
export function DubPanel({ dubs, buildDownloadUrl }: DubPanelProps) {
  if (dubs.length === 0) {
    return null;
  }

  return (
    <div className="pt-3 mt-3 border-t border-outline-variant/10">
      <div className="text-[10px] uppercase tracking-wider text-on-surface-variant mb-2">
        Generated dubs
      </div>
      <div className="flex flex-col gap-1 max-h-32 overflow-y-auto pr-1">
        {dubs.map((d) => {
          const href = buildDownloadUrl(d.filename);
          return (
            <div
              key={d.filename}
              className="flex items-center gap-2 px-2 py-1.5 rounded bg-surface-container-lowest"
            >
              <span className="text-[10px] font-mono font-semibold text-primary bg-primary/15 px-1.5 py-0.5 rounded">
                {d.version}
              </span>
              <span className="flex-1 text-xs text-on-surface truncate" title={`${d.voice} · ${d.provider}`}>
                {d.voice}
                <span className="text-on-surface-variant"> · {d.provider}</span>
              </span>
              {href && (
                <a
                  href={href}
                  download
                  title={`Download ${d.voice} (${d.provider})`}
                  className="p-1 rounded text-on-surface-variant hover:text-primary hover:bg-primary/10"
                  aria-label={`Download ${d.filename}`}
                >
                  <span className="material-symbols-outlined text-[14px]">download</span>
                </a>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
