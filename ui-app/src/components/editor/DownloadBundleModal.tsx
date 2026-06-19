import { useEffect, useMemo, useState } from 'react';
import type { TTSAudioEntry } from '../../api/client';
import { getRawVideoUrl, getSrtDownloadUrl, getTTSAudioUrl } from '../../api/client';
import type { VersionEntry } from '../../api/types';
import { safeFilename } from '../../utils/filename';

interface DownloadBundleModalProps {
  onClose: () => void;
  videoId: string;
  activeLang: string;
  videoTitle: string;
  versions: VersionEntry[];
  dubs: TTSAudioEntry[];
  /** SRT version currently loaded in the editor's preview picker
   *  ('draft' | 'v1' | 'v2' | ...). Seeds the modal's SRT version select
   *  so the user gets the version they're already looking at. */
  currentSrtVersion: string;
  /** Filename of the dub currently playing in the editor (or '' for
   *  source audio). When set, the modal pre-selects this dub. When '',
   *  the dub row is unchecked by default. */
  currentDubFilename: string;
}

type Asset = {
  enabled: boolean;
  /** href to download from (browser uses the BE's Content-Disposition fallback,
   *  but the local `download` attribute overrides for same-origin). */
  href: string;
  /** Final suggested filename presented to the browser. */
  filename: string;
};

/** Download bundle modal — pick a base name + the SRT version + the dub, click
 *  "Download all", and the browser saves the selected assets with the base
 *  name pattern. No backend zip — files arrive as separate downloads, which
 *  the browser triggers one after another with a tiny stagger to avoid the
 *  multi-download throttle on Chromium-based browsers. */
/** The parent is expected to mount this only when the modal should be open
 *  (i.e. `{bundleOpen && <DownloadBundleModal .../>}`). Each mount seeds
 *  fresh state from props — no reset effect needed. */
export function DownloadBundleModal({
  onClose,
  videoId,
  activeLang,
  videoTitle,
  versions,
  dubs,
  currentSrtVersion,
  currentDubFilename,
}: DownloadBundleModalProps) {
  // Base name seeds from the video's editable title; user can override.
  // Sanitised on input so the FE hint matches what the BE would set via
  // Content-Disposition.
  const defaultBase = useMemo(
    () => safeFilename(videoTitle, videoId),
    [videoTitle, videoId],
  );
  const [base, setBase] = useState(defaultBase);
  const [includeVideo, setIncludeVideo] = useState(true);
  const [includeSrt, setIncludeSrt] = useState(true);
  // Seed SRT version from whatever the editor is previewing right now —
  // the user's intent on Bundle-click is usually "give me what I see".
  const [srtVersion, setSrtVersion] = useState(() =>
    currentSrtVersion && (currentSrtVersion === 'draft' || versions.some((v) => v.id === currentSrtVersion))
      ? currentSrtVersion
      : 'draft',
  );
  // Same for the dub: pre-select whatever's playing in the editor. If the
  // editor has 'Source audio' selected ('' or no match), leave the dub row
  // unchecked and fall back to the first dub when the user enables it.
  const editorDubMatches =
    !!currentDubFilename && dubs.some((d) => d.filename === currentDubFilename);
  const [includeDub, setIncludeDub] = useState(editorDubMatches);
  const [dubFilename, setDubFilename] = useState(
    editorDubMatches ? currentDubFilename : (dubs[0]?.filename ?? ''),
  );
  const [downloading, setDownloading] = useState(false);

  // Esc-to-close.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const safeBase = safeFilename(base, videoId);

  // Each BE download route accepts a `download_as` query param that wins
  // over the server's title-based Content-Disposition. We MUST send it,
  // because most browsers honour Content-Disposition over the <a download>
  // attribute even on same-origin links — without download_as the file
  // arrives with the title-based name regardless of what `download="..."`
  // says on the anchor.
  const withDownloadAs = (baseUrl: string, name: string): string => {
    const sep = baseUrl.includes('?') ? '&' : '?';
    return `${baseUrl}${sep}download_as=${encodeURIComponent(name)}`;
  };

  // Compute filenames. Suffixes encode just enough to disambiguate when the
  // user downloads multiple snapshots / dubs to the same Downloads folder.
  const selectedDub = dubs.find((d) => d.filename === dubFilename);

  const videoName = `${safeBase}.mp4`;
  const srtName =
    srtVersion === 'draft'
      ? `${safeBase}.${activeLang}.srt`
      : `${safeBase}.${activeLang}.${srtVersion}.srt`;
  const dubName = selectedDub
    ? `${safeBase}.${activeLang}.${selectedDub.version}.${selectedDub.voice}.wav`
    : '';

  const videoAsset: Asset = {
    enabled: includeVideo,
    href: withDownloadAs(getRawVideoUrl(videoId), videoName),
    filename: videoName,
  };
  const srtAsset: Asset = {
    enabled: includeSrt && !!activeLang,
    href: activeLang
      ? withDownloadAs(getSrtDownloadUrl(videoId, activeLang, srtVersion), srtName)
      : '',
    filename: srtName,
  };
  const dubAsset: Asset = {
    enabled: includeDub && !!selectedDub && !!activeLang,
    href:
      selectedDub && activeLang
        ? withDownloadAs(getTTSAudioUrl(videoId, activeLang, selectedDub.filename), dubName)
        : '',
    filename: dubName,
  };

  const handleDownloadAll = async () => {
    const assets: Asset[] = [videoAsset, srtAsset, dubAsset].filter((a) => a.enabled && a.href);
    if (assets.length === 0) return;
    setDownloading(true);
    for (const asset of assets) {
      // Create a transient <a download> per asset; click it; remove it. The
      // 80ms stagger keeps Chrome from collapsing rapid clicks into a single
      // "Allow downloads from this site?" denial.
      const a = document.createElement('a');
      a.href = asset.href;
      a.download = asset.filename;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
    setDownloading(false);
    onClose();
  };

  const enabledCount = [videoAsset, srtAsset, dubAsset].filter((a) => a.enabled && a.href).length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md bg-surface-container rounded-xl shadow-xl p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-on-surface">Download bundle</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-on-surface-variant hover:bg-surface-container-high"
            aria-label="Close"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>

        {/* Base name */}
        <div className="space-y-1.5">
          <label className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
            Base name
          </label>
          <input
            value={base}
            onChange={(e) => setBase(e.target.value)}
            placeholder={videoId}
            className="w-full h-9 px-3 text-sm bg-surface-container-lowest text-on-surface rounded border-none focus:outline-none focus:ring-2 focus:ring-primary font-mono"
          />
          <p className="text-[10px] text-on-surface-variant">
            Each enabled file uses this base. The language, version, and voice are appended where needed so multiple downloads don't collide.
          </p>
        </div>

        {/* Video */}
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={includeVideo}
            onChange={(e) => setIncludeVideo(e.target.checked)}
            className="accent-primary"
          />
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium text-on-surface">Video (.mp4)</div>
            <div className="text-[10px] text-on-surface-variant truncate font-mono" title={videoAsset.filename}>
              → {videoAsset.filename}
            </div>
          </div>
        </label>

        {/* Subtitle */}
        <div className="space-y-1.5">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={includeSrt}
              onChange={(e) => setIncludeSrt(e.target.checked)}
              disabled={!activeLang}
              className="accent-primary"
            />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-on-surface">
                Subtitle (.srt)
                {!activeLang && <span className="text-on-surface-variant ml-2">— no language selected</span>}
              </div>
              <div className="text-[10px] text-on-surface-variant truncate font-mono" title={srtAsset.filename}>
                → {activeLang ? srtAsset.filename : '(disabled)'}
              </div>
            </div>
          </label>
          {includeSrt && activeLang && (
            <select
              value={srtVersion}
              onChange={(e) => setSrtVersion(e.target.value)}
              className="ml-8 h-8 px-2 text-xs bg-surface-container-lowest text-on-surface rounded border-none focus:outline-none focus:ring-2 focus:ring-primary"
              aria-label="Subtitle version to download"
            >
              <option value="draft">Working draft</option>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.id}
                  {v.name ? ` — ${v.name}` : ''}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Dub */}
        <div className="space-y-1.5">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={includeDub}
              onChange={(e) => setIncludeDub(e.target.checked)}
              disabled={dubs.length === 0 || !activeLang}
              className="accent-primary"
            />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-on-surface">
                Dub (.wav)
                {dubs.length === 0 && <span className="text-on-surface-variant ml-2">— no dubs available</span>}
              </div>
              <div className="text-[10px] text-on-surface-variant truncate font-mono" title={dubAsset.filename}>
                → {dubAsset.filename || '(disabled)'}
              </div>
            </div>
          </label>
          {includeDub && dubs.length > 0 && (
            <select
              value={dubFilename}
              onChange={(e) => setDubFilename(e.target.value)}
              className="ml-8 h-8 px-2 text-xs bg-surface-container-lowest text-on-surface rounded border-none focus:outline-none focus:ring-2 focus:ring-primary"
              aria-label="Dub to download"
            >
              {dubs.map((d) => (
                <option key={d.filename} value={d.filename}>
                  {d.version} · {d.voice} ({d.provider})
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="h-9 px-3 text-xs font-medium rounded bg-surface-container-high text-on-surface hover:bg-surface-container-highest"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleDownloadAll}
            disabled={downloading || enabledCount === 0}
            className="h-9 px-4 text-xs font-bold uppercase tracking-wider rounded bg-primary text-on-primary-fixed hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-[16px]">
              {downloading ? 'progress_activity' : 'download'}
            </span>
            <span>{downloading ? 'Downloading…' : `Download ${enabledCount} file${enabledCount === 1 ? '' : 's'}`}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
