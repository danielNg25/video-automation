import { TopBar } from '../components/TopBar';

function UploadPage() {
  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar showSearch={true} searchPlaceholder="Search projects..." />

      <main className="flex-1 overflow-y-auto">
        <div className="p-6 space-y-6 max-w-7xl mx-auto w-full">
          {/* Auth Status Bar */}
          <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-surface-container-low p-4 rounded-lg flex items-center justify-between border-l-2 border-emerald-500">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-red-900/20 text-red-500 flex items-center justify-center rounded">
                  <span className="material-symbols-outlined">video_library</span>
                </div>
                <div>
                  <p className="text-xs font-bold uppercase tracking-widest text-on-surface">YouTube</p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                    <span className="text-[10px] text-zinc-400 font-mono">CONNECTED: @videopro</span>
                  </div>
                </div>
              </div>
              <button className="text-[10px] font-bold text-zinc-500 uppercase tracking-tighter hover:text-on-surface">Switch</button>
            </div>
            <div className="bg-surface-container-low p-4 rounded-lg flex items-center justify-between border-l-2 border-emerald-500">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-zinc-900 text-zinc-100 flex items-center justify-center rounded">
                  <span className="material-symbols-outlined">music_video</span>
                </div>
                <div>
                  <p className="text-xs font-bold uppercase tracking-widest text-on-surface">TikTok</p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                    <span className="text-[10px] text-zinc-400 font-mono">CONNECTED: prod_main</span>
                  </div>
                </div>
              </div>
              <button className="text-[10px] font-bold text-zinc-500 uppercase tracking-tighter hover:text-on-surface">Switch</button>
            </div>
            <div className="bg-surface-container-low p-4 rounded-lg flex items-center justify-between border-l-2 border-error">
              <div className="flex items-center gap-3 opacity-60">
                <div className="w-10 h-10 bg-blue-900/20 text-blue-400 flex items-center justify-center rounded">
                  <span className="material-symbols-outlined">groups</span>
                </div>
                <div>
                  <p className="text-xs font-bold uppercase tracking-widest text-on-surface">Facebook</p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-error"></span>
                    <span className="text-[10px] text-zinc-400 font-mono">DISCONNECTED</span>
                  </div>
                </div>
              </div>
              <button className="bg-primary/10 text-primary px-3 py-1.5 rounded text-[10px] font-bold uppercase tracking-widest hover:bg-primary hover:text-on-primary-container transition-all">Connect</button>
            </div>
            <div className="bg-surface-container-low p-4 rounded-lg flex items-center justify-between border-l-2 border-error">
              <div className="flex items-center gap-3 opacity-60">
                <div className="w-10 h-10 bg-zinc-800 text-zinc-100 flex items-center justify-center rounded">
                  <span className="material-symbols-outlined">close</span>
                </div>
                <div>
                  <p className="text-xs font-bold uppercase tracking-widest text-on-surface">X / Twitter</p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-error"></span>
                    <span className="text-[10px] text-zinc-400 font-mono">DISCONNECTED</span>
                  </div>
                </div>
              </div>
              <button className="bg-primary/10 text-primary px-3 py-1.5 rounded text-[10px] font-bold uppercase tracking-widest hover:bg-primary hover:text-on-primary-container transition-all">Connect</button>
            </div>
          </section>

          {/* Upload Form */}
          <section className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            <div className="lg:col-span-4 space-y-6">
              <div className="bg-surface-container p-5 rounded-lg border border-outline-variant/10">
                <h3 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-4">1. Select Asset</h3>
                <div className="space-y-3">
                  <div className="bg-surface-container-lowest p-3 rounded flex items-center gap-4 cursor-pointer border border-primary/40 ring-1 ring-primary/20">
                    <div className="w-20 aspect-video bg-zinc-800 rounded overflow-hidden relative">
                      <div className="w-full h-full bg-surface-container-highest flex items-center justify-center">
                        <span className="material-symbols-outlined text-zinc-600">movie</span>
                      </div>
                      <div className="absolute inset-0 flex items-center justify-center bg-black/40">
                        <span className="material-symbols-outlined text-sm">play_arrow</span>
                      </div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-bold truncate">Project_Final_v2.mp4</p>
                      <p className="text-[10px] font-mono text-emerald-500 uppercase mt-0.5">Processed &bull; 4K HDR</p>
                    </div>
                    <span className="material-symbols-outlined text-primary" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  </div>
                  <div className="bg-surface-container-lowest p-3 rounded flex items-center gap-4 cursor-pointer hover:bg-surface-container-high transition-colors">
                    <div className="w-20 aspect-video bg-zinc-800 rounded overflow-hidden">
                      <div className="w-full h-full bg-surface-container-highest flex items-center justify-center opacity-50">
                        <span className="material-symbols-outlined text-zinc-600">movie</span>
                      </div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-zinc-500 truncate">Commercial_Draft_04.mp4</p>
                      <p className="text-[10px] font-mono text-zinc-600 uppercase mt-0.5">Processed &bull; 1080p</p>
                    </div>
                  </div>
                </div>
              </div>
              <div className="bg-surface-container p-5 rounded-lg border border-outline-variant/10">
                <h3 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-4">2. Destination</h3>
                <div className="space-y-2">
                  <label className="flex items-center justify-between p-3 rounded bg-surface-container-lowest cursor-pointer group">
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-zinc-500 group-hover:text-primary transition-colors">video_library</span>
                      <span className="text-xs font-medium">YouTube</span>
                    </div>
                    <input defaultChecked className="rounded border-outline-variant bg-transparent text-primary focus:ring-primary w-4 h-4" type="checkbox" />
                  </label>
                  <label className="flex items-center justify-between p-3 rounded bg-surface-container-lowest cursor-pointer group">
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-zinc-500 group-hover:text-primary transition-colors">music_video</span>
                      <span className="text-xs font-medium">TikTok</span>
                    </div>
                    <input defaultChecked className="rounded border-outline-variant bg-transparent text-primary focus:ring-primary w-4 h-4" type="checkbox" />
                  </label>
                  <label className="flex items-center justify-between p-3 rounded bg-surface-container-lowest opacity-40 cursor-not-allowed">
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-zinc-500">groups</span>
                      <span className="text-xs font-medium">Facebook</span>
                    </div>
                    <div className="text-[9px] font-mono text-error">OFFLINE</div>
                  </label>
                </div>
              </div>
            </div>

            {/* Metadata Editor */}
            <div className="lg:col-span-8 bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden flex flex-col h-full">
              <div className="flex border-b border-outline-variant/20 bg-surface-container-low">
                <button className="px-6 py-4 text-xs font-bold uppercase tracking-widest border-b-2 border-primary text-primary bg-surface-container">YouTube Settings</button>
                <button className="px-6 py-4 text-xs font-bold uppercase tracking-widest text-zinc-500 hover:text-on-surface transition-colors">TikTok Settings</button>
              </div>
              <div className="p-6 space-y-6 flex-1">
                <div className="space-y-2">
                  <div className="flex justify-between items-end">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">Video Title</label>
                    <span className="text-[10px] font-mono text-zinc-500">74 / 100</span>
                  </div>
                  <input className="w-full bg-surface-container-lowest border-none focus:ring-2 focus:ring-primary rounded p-3 text-sm" type="text" defaultValue="Testing the new precision engine for 4K video workflows | Production Log #12" />
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between items-end">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">Description</label>
                    <span className="text-[10px] font-mono text-error font-bold">5042 / 5000</span>
                  </div>
                  <textarea className="w-full h-40 bg-surface-container-lowest border border-error/30 focus:ring-2 focus:ring-error rounded p-3 text-sm resize-none" defaultValue="In this episode, we dive deep into the specific algorithmic improvements..." />
                </div>
                <div className="space-y-2">
                  <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">Tags (Separated by commas)</label>
                  <div className="flex flex-wrap gap-2 p-3 bg-surface-container-lowest rounded">
                    <div className="flex items-center gap-1.5 px-2 py-1 bg-surface-container-highest rounded text-[10px] font-mono border border-outline-variant/20">
                      <span>#videoediting</span>
                      <span className="material-symbols-outlined text-sm cursor-pointer hover:text-error">close</span>
                    </div>
                    <div className="flex items-center gap-1.5 px-2 py-1 bg-surface-container-highest rounded text-[10px] font-mono border border-outline-variant/20">
                      <span>#productivity</span>
                      <span className="material-symbols-outlined text-sm cursor-pointer hover:text-error">close</span>
                    </div>
                    <div className="flex items-center gap-1.5 px-2 py-1 bg-surface-container-highest rounded text-[10px] font-mono border border-outline-variant/20">
                      <span>#devlog</span>
                      <span className="material-symbols-outlined text-sm cursor-pointer hover:text-error">close</span>
                    </div>
                    <input className="bg-transparent border-none focus:ring-0 text-[10px] font-mono p-0 w-20" placeholder="Add..." type="text" />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">Privacy</label>
                    <select className="w-full bg-surface-container-lowest border-none focus:ring-2 focus:ring-primary rounded p-3 text-sm appearance-none" defaultValue="Unlisted">
                      <option>Public</option>
                      <option>Unlisted</option>
                      <option>Private</option>
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">Schedule</label>
                    <div className="flex items-center bg-surface-container-lowest rounded p-3 text-sm">
                      <span className="material-symbols-outlined text-sm text-zinc-500 mr-2">calendar_today</span>
                      <span className="text-zinc-500">ASAP (Immediate)</span>
                    </div>
                  </div>
                </div>
              </div>
              <div className="p-4 bg-surface-container-high flex justify-end gap-3 border-t border-outline-variant/10">
                <button className="px-6 py-2.5 text-xs font-bold uppercase tracking-widest text-zinc-400 hover:text-on-surface">Save Draft</button>
                <button className="px-10 py-2.5 bg-gradient-to-br from-primary to-primary-container text-on-primary-fixed font-black uppercase tracking-widest text-xs rounded active:scale-95 transition-all shadow-lg shadow-primary/20">
                  Execute Upload
                </button>
              </div>
            </div>
          </section>

          {/* Active Pipeline */}
          <section className="space-y-4">
            <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 flex items-center gap-2">
              <span className="material-symbols-outlined text-sm">sync</span> Active Pipeline
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* YouTube in progress */}
              <div className="bg-surface-container-low p-5 rounded-lg border border-outline-variant/10 flex flex-col gap-4">
                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-primary">video_library</span>
                    <div>
                      <h4 className="text-xs font-bold uppercase tracking-tighter">YouTube Upload</h4>
                      <p className="text-[10px] font-mono text-zinc-500">Task ID: 99x-102-YTB</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className="text-[10px] font-mono font-bold text-primary">45%</span>
                  </div>
                </div>
                <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden">
                  <div className="bg-primary h-full" style={{ width: '45%' }}></div>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex gap-4">
                    <div className="flex items-center gap-1.5">
                      <span className="material-symbols-outlined text-[10px] text-emerald-500" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                      <span className="text-[9px] font-mono text-zinc-400">AUTH</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <div className="w-2 h-2 rounded-full border border-primary border-t-transparent animate-spin"></div>
                      <span className="text-[9px] font-mono text-primary">UPLOADING...</span>
                    </div>
                    <div className="flex items-center gap-1.5 opacity-30">
                      <span className="material-symbols-outlined text-[10px]">circle</span>
                      <span className="text-[9px] font-mono">PROCESS</span>
                    </div>
                  </div>
                  <button className="text-[9px] font-bold uppercase tracking-widest text-error hover:underline">Cancel</button>
                </div>
              </div>

              {/* TikTok success */}
              <div className="bg-surface-container-low p-5 rounded-lg border border-outline-variant/10 flex flex-col gap-4">
                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-emerald-500">music_video</span>
                    <div>
                      <h4 className="text-xs font-bold uppercase tracking-tighter">TikTok Upload</h4>
                      <p className="text-[10px] font-mono text-emerald-500">SUCCESS: POSTED 2m ago</p>
                    </div>
                  </div>
                  <span className="material-symbols-outlined text-emerald-500" style={{ fontVariationSettings: "'FILL' 1" }}>verified</span>
                </div>
                <div className="flex items-center gap-4 mt-2">
                  <a className="flex-1 bg-surface-container-highest py-2 px-3 rounded flex items-center justify-between group hover:bg-zinc-700/50 transition-colors" href="#">
                    <span className="text-[10px] font-mono truncate max-w-[200px]">tiktok.com/v/921820...</span>
                    <span className="material-symbols-outlined text-sm text-zinc-500 group-hover:text-on-surface">open_in_new</span>
                  </a>
                  <button className="px-4 py-2 bg-surface-container-highest rounded text-[10px] font-bold uppercase tracking-widest hover:text-primary">Analytics</button>
                </div>
              </div>
            </div>

            {/* Error banner */}
            <div className="bg-error-container/10 border border-error/20 p-4 rounded-lg flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="bg-error/20 text-error p-2 rounded">
                  <span className="material-symbols-outlined">warning</span>
                </div>
                <div>
                  <p className="text-xs font-bold text-on-error-container uppercase tracking-tight">X / Twitter Upload Failed</p>
                  <p className="text-[10px] font-mono text-error/80">API ERROR 401: Invalid Credentials. Please re-authenticate account.</p>
                </div>
              </div>
              <div className="flex gap-2">
                <button className="bg-error/20 text-error px-4 py-1.5 rounded text-[10px] font-black uppercase tracking-widest hover:bg-error hover:text-on-error transition-all">Retry Now</button>
                <button className="text-zinc-500 hover:text-on-surface p-1.5">
                  <span className="material-symbols-outlined text-sm">close</span>
                </button>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

export default UploadPage;
