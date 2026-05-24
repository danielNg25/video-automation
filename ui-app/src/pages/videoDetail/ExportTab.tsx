import { useState, useEffect, useRef } from 'react';
import {
  postExportPreview, getExportedVideoUrl, getExportStatus,
} from '../../api/client';
import type { TTSAudioEntry } from '../../api/client';
import type { VideoMetadata } from '../../api/types';

interface Props {
  video: VideoMetadata;
  ttsList: TTSAudioEntry[];
  // Export action + state owned by the parent so SSE wiring lives next to
  // the other pipeline handlers in VideoDetail.
  onExport: (params: {
    subtitleLanguage: string | null;
    ttsFile: string | null;
    videoVolume: number;
    ttsVolume: number;
  }) => Promise<void>;
  isExporting: boolean;
  exportProgress: { pct: number; message: string };
  exportDone: boolean;
  exportError: string;
  exportTimestamp: number;
  onExportTimestampSync: (ts: number) => void;
  onExportDoneSync: (done: boolean) => void;
}

export function ExportTab(props: Props) {
  const {
    video, ttsList,
    onExport, isExporting, exportProgress, exportDone, exportError,
    exportTimestamp, onExportTimestampSync, onExportDoneSync,
  } = props;

  const videoId = video.video_id;
  const srtLanguages = video.srt_languages || [];
  const defaultLang = srtLanguages.find((l) => l !== 'zh') || srtLanguages[0] || '';

  const [language, setLanguage] = useState(defaultLang);
  const [selectedTtsFile, setSelectedTtsFile] = useState<string | null>(ttsList[0]?.filename ?? null);
  const [videoVol, setVideoVol] = useState(30);
  const [dubVol, setDubVol] = useState(100);

  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState('');

  const [showExportModal, setShowExportModal] = useState(false);

  // Auto-select first TTS file when the list changes
  useEffect(() => {
    if (ttsList.length > 0 && !selectedTtsFile) {
      setSelectedTtsFile(ttsList[0].filename);
    }
    if (ttsList.length === 0 && selectedTtsFile) {
      setSelectedTtsFile(null);
    }
  }, [ttsList, selectedTtsFile]);

  // Update default language if srt_languages changes (e.g. after translation)
  useEffect(() => {
    if (!language && defaultLang) setLanguage(defaultLang);
  }, [defaultLang, language]);

  // Check if an export already exists on first mount
  const exportChecked = useRef(false);
  useEffect(() => {
    if (exportChecked.current) return;
    exportChecked.current = true;
    getExportStatus(videoId).then((status) => {
      if (status.exists) {
        onExportDoneSync(true);
        onExportTimestampSync(status.modified ? Math.round(status.modified * 1000) : Date.now());
      }
    }).catch(() => {});
  }, [videoId, onExportDoneSync, onExportTimestampSync]);

  // Cleanup preview blob URL
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  const handlePreview = async () => {
    setIsPreviewing(true); setPreviewError('');
    try {
      const blob = await postExportPreview(videoId, language || null, selectedTtsFile, videoVol / 100, dubVol / 100);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleExportClick = () => {
    if (isExporting) return;
    onExport({
      subtitleLanguage: language || null,
      ttsFile: selectedTtsFile,
      videoVolume: videoVol / 100,
      ttsVolume: dubVol / 100,
    });
  };

  if (!video.has_srt) {
    return (
      <div className="bg-surface-container-low rounded-xl p-6 border border-outline-variant/10 text-center text-on-surface-variant text-sm">
        Transcribe the video first to enable export.
      </div>
    );
  }

  const exportedUrl = `${getExportedVideoUrl(videoId)}?t=${exportTimestamp}`;

  return (
    <div className="space-y-6">
      {/* Configuration card */}
      <div className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/10 space-y-4">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-primary text-lg">output</span>
          <h3 className="text-sm font-bold uppercase tracking-widest text-on-surface">Export</h3>
          <span className="ml-auto text-[10px] font-mono text-zinc-500">
            {video.resolution} · {video.size} · {video.codec}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Subtitle Language</label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-0"
            >
              {srtLanguages.length === 0 && <option value="">No subtitles</option>}
              {srtLanguages.map((l) => (
                <option key={l} value={l}>
                  {l === 'en' ? 'English' : l === 'vi' ? 'Vietnamese' : l === 'zh' ? 'Chinese' : l.toUpperCase()}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Dub Audio</label>
            <select
              value={selectedTtsFile || ''}
              onChange={(e) => setSelectedTtsFile(e.target.value || null)}
              className="w-full bg-surface-container-highest border-none text-xs text-on-surface py-1.5 px-2 rounded focus:ring-0"
            >
              <option value="">No dub</option>
              {ttsList.map((entry) => (
                <option key={entry.filename} value={entry.filename}>
                  {entry.voice} ({entry.provider} · {entry.language})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <div className="flex justify-between">
              <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Video Volume</label>
              <span className="text-[10px] font-mono text-primary">{videoVol}%</span>
            </div>
            <input
              type="range" min={0} max={200} value={videoVol}
              onChange={(e) => setVideoVol(Number(e.target.value))}
              className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
            />
          </div>
          <div className="space-y-1">
            <div className="flex justify-between">
              <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Dub Volume</label>
              <span className="text-[10px] font-mono text-primary">{dubVol}%</span>
            </div>
            <input
              type="range" min={0} max={200} value={dubVol}
              onChange={(e) => setDubVol(Number(e.target.value))}
              disabled={!selectedTtsFile}
              className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer disabled:opacity-50"
            />
          </div>
        </div>

        <div className="flex gap-2">
          <button
            onClick={handlePreview}
            disabled={isPreviewing || isExporting}
            className="flex-1 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 bg-surface-container-highest text-on-surface hover:bg-surface-container-high transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">{isPreviewing ? 'progress_activity' : 'preview'}</span>
            {isPreviewing ? 'Rendering…' : 'Preview 5s'}
          </button>
          <button
            onClick={handleExportClick}
            disabled={isExporting}
            className="flex-1 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 bg-gradient-to-r from-primary to-primary-container text-on-primary-fixed hover:shadow-[0_0_20px_rgba(160,120,255,0.3)] transition-all disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-sm">{isExporting ? 'progress_activity' : 'movie_edit'}</span>
            {isExporting ? 'Exporting…' : exportDone ? 'Re-Export' : 'Export'}
          </button>
        </div>

        {isExporting && (
          <div className="space-y-1">
            <div className="flex justify-between text-[10px] font-mono">
              <span className="text-on-surface-variant">{exportProgress.message}</span>
              <span className="text-primary">{exportProgress.pct}%</span>
            </div>
            <div className="h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
              <div className="h-full bg-primary transition-all duration-300" style={{ width: `${exportProgress.pct}%` }} />
            </div>
          </div>
        )}

        {(previewError || exportError) && (
          <div className="p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
            {previewError || exportError}
          </div>
        )}

        {previewUrl && !exportDone && (
          <div className="space-y-1">
            <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Preview</label>
            <video controls autoPlay className="w-full rounded-lg bg-black" src={previewUrl} />
          </div>
        )}
      </div>

      {/* Exported file actions */}
      {exportDone && (
        <div className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/10 space-y-3">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-emerald-400 text-lg">check_circle</span>
            <h3 className="text-sm font-bold uppercase tracking-widest text-on-surface">Exported file</h3>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => setShowExportModal(true)}
              className="flex items-center gap-2 px-3 py-1.5 rounded text-xs font-bold uppercase tracking-wider bg-surface-container-highest text-on-surface hover:bg-surface-container-high transition-colors"
            >
              <span className="material-symbols-outlined text-sm">play_circle</span>
              View
            </button>
            <a
              href={exportedUrl}
              download
              className="flex items-center gap-2 px-3 py-1.5 rounded text-xs font-bold uppercase tracking-wider bg-primary/20 text-primary hover:bg-primary/30 transition-colors"
            >
              <span className="material-symbols-outlined text-sm">download</span>
              Download
            </a>
          </div>
        </div>
      )}

      {/* Exported-video modal */}
      {showExportModal && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-8" onClick={() => setShowExportModal(false)}>
          <div className="bg-surface-container rounded-xl border border-outline-variant/10 max-w-2xl w-full overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant/10">
              <span className="text-sm font-medium text-on-surface">Exported Video</span>
              <div className="flex items-center gap-2">
                <a
                  href={exportedUrl}
                  download
                  className="text-[10px] font-bold text-primary hover:underline flex items-center gap-1"
                >
                  <span className="material-symbols-outlined text-sm">download</span>
                  Download
                </a>
                <button onClick={() => setShowExportModal(false)} className="text-on-surface-variant hover:text-on-surface">
                  <span className="material-symbols-outlined">close</span>
                </button>
              </div>
            </div>
            <div className="p-4 flex justify-center">
              <video controls autoPlay className="max-w-full max-h-[75vh] rounded-lg bg-black" src={exportedUrl} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
