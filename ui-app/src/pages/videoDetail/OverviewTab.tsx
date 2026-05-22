import { useNavigate } from 'react-router-dom';
import type { VideoMetadata } from '../../api/types';
import { getRawVideoUrl } from '../../api/client';

interface Props {
  video: VideoMetadata;
  editingTitle: boolean;
  titleDraft: string;
  isTranscribing: boolean;
  transcribeMessage: string;
  onStartTitleEdit: () => void;
  onChangeTitleDraft: (v: string) => void;
  onSaveTitle: () => void;
  onCancelTitleEdit: () => void;
  onTranscribe: () => void;
}

function statusBadge(status: string) {
  if (status === 'exported') return { text: 'EXPORTED', cls: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' };
  if (status === 'translated') return { text: 'TRANSLATED', cls: 'bg-blue-500/10 text-blue-400 border-blue-500/20' };
  return { text: 'TRANSCRIBED', cls: 'bg-primary/10 text-primary border-primary/20' };
}

function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export function OverviewTab(props: Props) {
  const navigate = useNavigate();
  const {
    video, editingTitle, titleDraft, isTranscribing, transcribeMessage,
    onStartTitleEdit, onChangeTitleDraft, onSaveTitle, onCancelTitleEdit,
    onTranscribe,
  } = props;
  const badge = statusBadge(video.status);

  return (
    <div className="space-y-6">
      <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
        <div className="p-5 flex gap-5">
          {video.thumbnail ? (
            <img src={video.thumbnail} alt={video.title} className="w-48 aspect-video rounded-lg object-cover bg-surface-container-highest" />
          ) : (
            <div className="w-48 aspect-video rounded-lg bg-surface-container-highest flex items-center justify-center">
              <span className="material-symbols-outlined text-3xl text-zinc-600">movie</span>
            </div>
          )}
          <div className="flex-1 min-w-0 space-y-3">
            <div className="flex items-start gap-2">
              {editingTitle ? (
                <>
                  <input
                    autoFocus
                    value={titleDraft}
                    onChange={(e) => onChangeTitleDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') onSaveTitle(); if (e.key === 'Escape') onCancelTitleEdit(); }}
                    className="flex-1 bg-surface-container-highest border-none text-base font-medium text-on-surface py-1 px-2 rounded focus:ring-1 focus:ring-primary"
                  />
                  <button onClick={onSaveTitle} className="text-[10px] font-bold uppercase text-primary px-2 py-1">Save</button>
                  <button onClick={onCancelTitleEdit} className="text-[10px] font-bold uppercase text-zinc-500 px-2 py-1">Cancel</button>
                </>
              ) : (
                <>
                  <h2 className="text-base font-medium text-on-surface flex-1 leading-tight">{video.title || video.video_id}</h2>
                  <button onClick={onStartTitleEdit} className="text-zinc-500 hover:text-on-surface" title="Edit title">
                    <span className="material-symbols-outlined text-sm">edit</span>
                  </button>
                </>
              )}
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${badge.cls}`}>{badge.text}</span>
              {video.srt_languages.map((lang) => (
                <span key={lang} className="text-[10px] font-mono bg-surface-container-highest px-1.5 py-0.5 rounded uppercase">{lang}</span>
              ))}
            </div>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
              <dt className="text-on-surface-variant">Video ID</dt><dd className="font-mono">{video.video_id}</dd>
              <dt className="text-on-surface-variant">Resolution</dt><dd className="font-mono">{video.resolution || '—'}</dd>
              <dt className="text-on-surface-variant">Codec</dt><dd className="font-mono">{video.codec || '—'}</dd>
              <dt className="text-on-surface-variant">Size</dt><dd className="font-mono">{video.size || '—'}</dd>
              <dt className="text-on-surface-variant">Duration</dt><dd className="font-mono">{formatDuration(video.duration)}</dd>
            </dl>

            <div className="flex flex-wrap gap-2 pt-2">
              {video.has_srt ? (
                <>
                  <button
                    onClick={() => navigate(`/editor/${video.video_id}`)}
                    className="bg-primary text-on-primary-fixed px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 active:scale-95 transition-all"
                  >
                    <span className="material-symbols-outlined text-sm">edit_note</span>
                    Open Editor
                  </button>
                  <button
                    onClick={onTranscribe}
                    className="bg-surface-container-highest text-on-surface px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 hover:bg-surface-container-high active:scale-95 transition-all"
                  >
                    <span className="material-symbols-outlined text-sm">refresh</span>
                    Re-extract subtitles
                  </button>
                </>
              ) : (
                <button
                  onClick={onTranscribe}
                  disabled={isTranscribing}
                  className="bg-primary text-on-primary-fixed px-6 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 active:scale-95 transition-all disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-sm">document_scanner</span>
                  Extract subtitles
                </button>
              )}
              <a
                href={getRawVideoUrl(video.video_id)}
                download
                className="bg-surface-container-highest text-on-surface px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 hover:bg-surface-container-high active:scale-95 transition-all"
              >
                <span className="material-symbols-outlined text-sm">save_alt</span>
                Download MP4
              </a>
            </div>
          </div>
        </div>
      </div>

      {isTranscribing && (
        <div className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/10">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-full border-2 border-primary border-t-transparent animate-spin" />
            <div className="flex-1">
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs font-bold uppercase tracking-widest text-primary">Extracting subtitles (OCR)…</span>
                <span className="text-[10px] font-mono text-zinc-500">PADDLEOCR</span>
              </div>
              <p className="text-[11px] font-medium text-emerald-400">{transcribeMessage}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
