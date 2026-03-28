import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { getVideos, deleteVideo } from '../api/client';
import type { VideoMetadata } from '../api/types';

function formatDuration(seconds: number): string {
  if (!seconds) return '--:--';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function VideoListPage() {
  const navigate = useNavigate();
  const [videos, setVideos] = useState<VideoMetadata[]>([]);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [deleting, setDeleting] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await getVideos();
      setVideos(res.videos);
    } catch {
      // API not available
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const filteredVideos = videos.filter((v) => {
    if (filter === 'transcribed' && !v.has_srt) return false;
    if (filter === 'downloaded' && v.has_srt) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        v.title.toLowerCase().includes(q) ||
        v.video_id.toLowerCase().includes(q) ||
        v.author.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const handleDelete = async (videoId: string) => {
    if (!confirm(`Delete video ${videoId} and all associated files?`)) return;
    setDeleting(videoId);
    try {
      await deleteVideo(videoId);
      setVideos((prev) => prev.filter((v) => v.video_id !== videoId));
    } catch {
      // ignore
    } finally {
      setDeleting(null);
    }
  };

  const statusBadge = (v: VideoMetadata) => {
    if (v.status === 'processed') return { text: 'Processed', cls: 'bg-emerald-900/30 text-emerald-400' };
    if (v.has_srt) return { text: 'Transcribed', cls: 'bg-primary/20 text-primary' };
    return { text: 'Downloaded', cls: 'bg-zinc-700/40 text-zinc-400' };
  };

  return (
    <div className="flex flex-col h-full">
      <TopBar showSearch={false} />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-on-surface">Video Studio</h1>
            <p className="text-xs text-on-surface-variant mt-1">{videos.length} videos in library</p>
          </div>
          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Search videos..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-surface-container-lowest border border-outline-variant/20 rounded-md px-3 py-2 text-xs w-64 focus:ring-1 focus:ring-primary placeholder:text-zinc-600"
            />
            <div className="flex bg-surface-container-lowest p-1 rounded-md">
              {['all', 'downloaded', 'transcribed'].map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1 text-[10px] uppercase font-bold tracking-tighter ${
                    filter === f
                      ? 'bg-surface-container-high text-primary rounded-sm'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Video Grid */}
        {filteredVideos.length === 0 ? (
          <div className="text-center py-20">
            <span className="material-symbols-outlined text-4xl text-zinc-600 mb-3 block">video_library</span>
            <p className="text-zinc-500 text-sm">
              {videos.length === 0
                ? 'No videos yet. Download one from the Pipeline page.'
                : 'No videos match your filter.'}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredVideos.map((v) => {
              const badge = statusBadge(v);
              return (
                <div
                  key={v.video_id}
                  className="bg-surface-container-low rounded-lg overflow-hidden hover:bg-surface-container transition-colors group cursor-pointer"
                  onClick={() => navigate(`/videos/${v.video_id}`)}
                >
                  {/* Thumbnail */}
                  <div className="aspect-video bg-surface-container-highest relative flex items-center justify-center">
                    {v.thumbnail ? (
                      <img src={v.thumbnail} alt={v.title} className="w-full h-full object-cover" />
                    ) : (
                      <span className="material-symbols-outlined text-3xl text-zinc-600">movie</span>
                    )}
                    {/* Duration badge */}
                    {v.duration > 0 && (
                      <span className="absolute bottom-1.5 right-1.5 bg-black/70 text-white text-[10px] font-mono px-1.5 py-0.5 rounded">
                        {formatDuration(v.duration)}
                      </span>
                    )}
                  </div>

                  {/* Info */}
                  <div className="p-3 space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-sm font-medium text-on-surface line-clamp-2 leading-tight">
                        {v.title || `${v.video_id}.mp4`}
                      </h3>
                    </div>

                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${badge.cls}`}>
                        {badge.text}
                      </span>
                      {v.srt_languages.map((lang) => (
                        <span key={lang} className="text-[9px] font-mono bg-surface-container-highest text-zinc-400 px-1.5 py-0.5 rounded">
                          {lang}
                        </span>
                      ))}
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-zinc-500">
                      <span className="font-mono">{v.video_id.slice(0, 10)}</span>
                      <span>{v.size}</span>
                    </div>

                    {/* Actions */}
                    <div className="flex gap-2 pt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/videos/${v.video_id}`);
                        }}
                        className="flex-1 py-1.5 text-[10px] font-bold uppercase bg-primary/10 text-primary rounded hover:bg-primary/20 transition-colors"
                      >
                        Open Studio
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/editor/${v.video_id}`);
                        }}
                        className="py-1.5 px-3 text-[10px] font-bold uppercase bg-surface-container-highest text-zinc-400 rounded hover:text-on-surface transition-colors"
                      >
                        Edit Subs
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(v.video_id);
                        }}
                        disabled={deleting === v.video_id}
                        className="py-1.5 px-2 text-[10px] text-zinc-500 hover:text-error transition-colors"
                      >
                        <span className="material-symbols-outlined text-sm">delete</span>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
