import { TopBar } from '../components/TopBar';
import { srtSegments, recentDownloads } from '../data/mockData';

function DownloadTranscribePage() {
  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb="Transcribe" />

      <section className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* URL Input Section */}
        <div className="bg-surface-container-low p-1 rounded-xl shadow-sm">
          <div className="flex items-center bg-surface-container-lowest p-2 rounded-lg gap-3 focus-within:ring-1 focus-within:ring-primary/40 transition-shadow">
            <div className="pl-3 text-on-surface-variant">
              <span className="material-symbols-outlined">link</span>
            </div>
            <input
              className="flex-1 bg-transparent border-none focus:ring-0 text-on-surface placeholder:text-zinc-600 text-sm py-3"
              placeholder="Paste Douyin share link or URL"
              type="text"
            />
            <button className="bg-primary text-on-primary-fixed px-6 py-2.5 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 hover:brightness-110 active:scale-95 transition-all">
              <span>Download</span>
              <span className="material-symbols-outlined text-sm">download</span>
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column */}
          <div className="lg:col-span-7 space-y-6">
            {/* Active Download Card */}
            <div className="bg-surface-container-low rounded-xl overflow-hidden">
              <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-lg">downloading</span>
                  <span className="text-xs font-bold uppercase tracking-widest">Active Download</span>
                </div>
                <span className="text-[10px] font-mono text-zinc-500">ENGINE: YT-DLP (STABLE)</span>
              </div>
              <div className="p-5 space-y-4">
                <div className="flex justify-between items-end mb-1">
                  <div className="space-y-1">
                    <div className="text-sm font-semibold truncate max-w-[300px]">douyin_video_7283941203.mp4</div>
                    <div className="text-[10px] text-zinc-500 font-mono uppercase">Merging Fragments...</div>
                  </div>
                  <div className="text-right">
                    <div className="text-lg font-black font-mono text-primary tracking-tighter">74.2%</div>
                    <div className="text-[10px] text-zinc-500 font-mono">12.4 MB/s &bull; ETA: 00:08</div>
                  </div>
                </div>
                <div className="w-full bg-surface-container-highest h-1.5 rounded-full overflow-hidden">
                  <div className="bg-primary h-full w-[74.2%] transition-all duration-500 shadow-[0_0_8px_rgba(208,188,255,0.4)]"></div>
                </div>
              </div>
            </div>

            {/* Video Result Card */}
            <div className="bg-surface-container-low rounded-xl overflow-hidden flex flex-col md:flex-row border border-primary/20">
              <div className="w-full md:w-64 aspect-video bg-surface-container-highest relative group">
                <div className="w-full h-full bg-surface-container-highest flex items-center justify-center">
                  <span className="material-symbols-outlined text-4xl text-zinc-600">movie</span>
                </div>
                <div className="absolute bottom-2 right-2 bg-black/80 text-white text-[10px] px-1.5 py-0.5 rounded font-mono">04:12</div>
                <div className="absolute inset-0 bg-primary/10 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                  <span className="material-symbols-outlined text-3xl">play_circle</span>
                </div>
              </div>
              <div className="flex-1 p-5 flex flex-col justify-between">
                <div>
                  <div className="flex justify-between items-start mb-2">
                    <h3 className="text-sm font-bold leading-tight">Exploring the Neo-Tokyo Aesthetics: A Visual Journey Through Shinjuku</h3>
                    <span className="bg-emerald-500/10 text-emerald-400 text-[10px] px-2 py-0.5 rounded-full border border-emerald-500/20 font-bold">COMPLETED</span>
                  </div>
                  <div className="grid grid-cols-2 gap-y-2 gap-x-4">
                    <div className="flex flex-col">
                      <span className="text-[10px] text-zinc-500 uppercase tracking-tighter">Author</span>
                      <span className="text-xs font-medium">@cyber_explorer</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[10px] text-zinc-500 uppercase tracking-tighter">Resolution</span>
                      <span className="text-xs font-medium font-mono">1080x1920 (9:16)</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[10px] text-zinc-500 uppercase tracking-tighter">Size</span>
                      <span className="text-xs font-medium font-mono">42.8 MB</span>
                    </div>
                    <div className="flex flex-col">
                      <span className="text-[10px] text-zinc-500 uppercase tracking-tighter">Codec</span>
                      <span className="text-xs font-medium font-mono">h.264 / AAC</span>
                    </div>
                  </div>
                </div>
                <div className="mt-6 flex items-center gap-3">
                  <div className="flex-1 flex gap-px rounded-md overflow-hidden border border-outline-variant/20">
                    <select className="flex-1 bg-surface-container-highest border-none text-xs text-on-surface py-2 px-3 focus:ring-0">
                      <option>Chinese (Mandarin)</option>
                      <option>Chinese + English</option>
                      <option>English Only</option>
                    </select>
                  </div>
                  <button className="bg-primary text-on-primary-fixed px-4 py-2 rounded-md font-bold text-xs uppercase tracking-wider flex items-center gap-2 whitespace-nowrap active:scale-95 transition-all">
                    <span>Transcribe</span>
                    <span className="material-symbols-outlined text-sm">neurology</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Transcription Progress */}
            <div className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/10">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-full border-2 border-primary border-t-transparent animate-spin"></div>
                <div className="flex-1">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-xs font-bold uppercase tracking-widest text-primary">Transcribing Audio...</span>
                    <span className="text-[10px] font-mono text-zinc-500">WHISPER v3 LARGE</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-on-surface-variant font-mono">Current Stage:</span>
                    <span className="text-[11px] font-medium text-emerald-400">Loading model weights to GPU...</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: SRT Preview */}
          <div className="lg:col-span-5 h-full flex flex-col min-h-[500px]">
            <div className="bg-surface-container-low rounded-xl flex-1 flex flex-col border border-outline-variant/10">
              <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center bg-surface-container-high/30">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-zinc-400">subtitles</span>
                  <span className="text-xs font-bold uppercase tracking-widest">SRT Preview</span>
                </div>
                <div className="flex gap-2">
                  <button className="p-1.5 hover:bg-surface-container-highest rounded transition-colors text-zinc-400" title="Export SRT">
                    <span className="material-symbols-outlined text-sm">download</span>
                  </button>
                  <button className="p-1.5 hover:bg-surface-container-highest rounded transition-colors text-zinc-400" title="Copy Text">
                    <span className="material-symbols-outlined text-sm">content_copy</span>
                  </button>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-2 space-y-1">
                {/* Segment entries */}
                {srtSegments.map((seg) => (
                  <div
                    key={seg.id}
                    className="group p-3 rounded hover:bg-surface-container-high transition-colors cursor-pointer border-l-2 border-transparent hover:border-primary"
                  >
                    <div className="flex justify-between mb-1">
                      <span className="text-[10px] font-mono text-primary font-bold">{seg.startTime} → {seg.endTime}</span>
                      <span className="text-[10px] text-zinc-600 font-mono">#{seg.id}</span>
                    </div>
                    <p className="text-xs leading-relaxed text-on-surface-variant group-hover:text-on-surface">{seg.text}</p>
                  </div>
                ))}
                {/* Loading skeleton */}
                <div className="p-3 opacity-30">
                  <div className="h-2 w-24 bg-surface-container-highest rounded mb-2"></div>
                  <div className="h-3 w-full bg-surface-container-highest rounded mb-1"></div>
                  <div className="h-3 w-2/3 bg-surface-container-highest rounded"></div>
                </div>
              </div>
              <div className="p-4 bg-surface-container-highest/20 border-t border-outline-variant/10">
                <button className="w-full py-2 bg-outline-variant/20 hover:bg-outline-variant/40 rounded-md text-[10px] font-bold uppercase tracking-widest transition-colors">
                  Open Full Editor
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Recent Downloads */}
        <div className="space-y-4 pt-6">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold uppercase tracking-[0.2em] text-zinc-500">Recent Downloads</h2>
            <button className="text-[10px] font-bold text-primary hover:underline">VIEW HISTORY</button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {recentDownloads.map((item) => (
              <div
                key={item.id}
                className="bg-surface-container-lowest p-3 rounded-lg flex items-center gap-4 hover:bg-surface-container-low transition-colors group border border-outline-variant/5"
              >
                <div className="w-16 h-10 bg-surface-container-high rounded overflow-hidden flex-shrink-0 relative">
                  {item.status === 'failed' ? (
                    <div className="absolute inset-0 bg-error/20 flex items-center justify-center">
                      <span className="material-symbols-outlined text-error text-sm">error</span>
                    </div>
                  ) : (
                    <div className="w-full h-full bg-surface-container-highest flex items-center justify-center">
                      <span className="material-symbols-outlined text-sm text-zinc-600">movie</span>
                    </div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className={`text-[11px] font-bold truncate${item.status === 'failed' ? ' text-error/80' : ''}`}>{item.filename}</div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[9px] font-mono text-zinc-500">{item.size}</span>
                    <span className="w-1 h-1 rounded-full bg-zinc-700"></span>
                    <span
                      className={`text-[9px] font-bold uppercase ${
                        item.status === 'success'
                          ? 'text-emerald-500'
                          : item.status === 'transcribing'
                            ? 'text-primary'
                            : 'text-error'
                      }`}
                    >
                      {item.status === 'success'
                        ? 'Success'
                        : item.status === 'transcribing'
                          ? 'Transcribing'
                          : 'Failed'}
                    </span>
                  </div>
                </div>
                <button className="opacity-0 group-hover:opacity-100 material-symbols-outlined text-sm text-zinc-500 hover:text-on-surface">more_vert</button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Floating Status Indicator */}
      <div className="fixed bottom-6 right-6 z-[100] bg-surface-container-highest/80 backdrop-blur-xl border border-outline-variant/30 px-4 py-2 rounded-full shadow-2xl flex items-center gap-3">
        <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
        <span className="text-[10px] font-bold font-mono uppercase tracking-widest text-on-surface">Worker Node 04: Active</span>
        <div className="h-3 w-px bg-outline-variant/30"></div>
        <span className="text-[10px] font-mono text-primary">GPU Util: 42%</span>
      </div>
    </div>
  );
}

export default DownloadTranscribePage;
