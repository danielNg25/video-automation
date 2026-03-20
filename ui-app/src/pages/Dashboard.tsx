import { useState } from 'react';
import { TopBar } from '../components/TopBar';

const filterTabs = ['All', 'Running', 'Completed', 'Failed'] as const;

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<string>('All');

  return (
    <div className="flex flex-col h-full">
      <TopBar showSearch searchPlaceholder="Search tasks, videos or logs..." />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Stats Row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-surface-container-low p-4 rounded-lg flex flex-col gap-1 group hover:bg-surface-container transition-colors">
            <span className="text-xs text-on-surface-variant font-medium uppercase tracking-wider">Total Videos</span>
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-mono font-semibold text-on-surface">1,284</span>
              <span className="text-[10px] font-mono text-emerald-500">+12.5%</span>
            </div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-lg flex flex-col gap-1 group hover:bg-surface-container transition-colors">
            <span className="text-xs text-on-surface-variant font-medium uppercase tracking-wider">Processed Today</span>
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-mono font-semibold text-on-surface">42</span>
              <span className="text-[10px] font-mono text-primary">Target: 50</span>
            </div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-lg flex flex-col gap-1 group hover:bg-surface-container transition-colors">
            <span className="text-xs text-on-surface-variant font-medium uppercase tracking-wider">Success Rate</span>
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-mono font-semibold text-on-surface">98.2%</span>
              <div className="flex gap-0.5">
                <div className="w-1 h-3 bg-emerald-500/40 rounded-full"></div>
                <div className="w-1 h-4 bg-emerald-500/60 rounded-full"></div>
                <div className="w-1 h-5 bg-emerald-500 rounded-full"></div>
              </div>
            </div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-lg flex flex-col gap-1 group hover:bg-surface-container transition-colors">
            <span className="text-xs text-on-surface-variant font-medium uppercase tracking-wider">Active Tasks</span>
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-mono font-semibold text-primary">07</span>
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
              </span>
            </div>
          </div>
        </div>

        {/* Middle Section */}
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Pipeline Table (60%) */}
          <div className="lg:w-[60%] space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-title-sm font-semibold text-on-surface">Pipeline Status</h2>
              <div className="flex bg-surface-container-lowest p-1 rounded-md">
                {filterTabs.map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-3 py-1 text-[10px] uppercase font-bold tracking-tighter ${
                      activeTab === tab
                        ? 'bg-surface-container-high text-primary rounded-sm'
                        : 'text-on-surface-variant hover:text-on-surface'
                    }`}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            </div>
            <div className="bg-surface-container-low rounded-lg overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="text-[10px] uppercase tracking-widest text-on-surface-variant border-b border-outline-variant/10">
                    <th className="px-4 py-3 font-semibold">Thumbnail &amp; Title</th>
                    <th className="px-4 py-3 font-semibold text-center">Pipeline</th>
                    <th className="px-4 py-3 font-semibold">Platform</th>
                    <th className="px-4 py-3 font-semibold">Started</th>
                    <th className="px-4 py-3 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="text-xs">
                  {/* Row 1: In Progress */}
                  <tr className="hover:bg-surface-container-high/50 transition-colors group">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-12 h-8 rounded bg-surface-container-highest overflow-hidden relative">
                          <div className="w-full h-full bg-surface-container-highest flex items-center justify-center">
                            <span className="material-symbols-outlined text-xs text-zinc-600">movie</span>
                          </div>
                        </div>
                        <div className="flex flex-col">
                          <span className="font-medium text-on-surface line-clamp-1">Product_Demo_Final_v2.mp4</span>
                          <span className="font-mono text-[9px] text-on-surface-variant uppercase">ID: 8219-AX</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-center gap-1.5">
                        <div className="w-2 h-2 rounded-full bg-emerald-500" title="Download"></div>
                        <div className="w-2 h-2 rounded-full bg-emerald-500" title="Transcribe"></div>
                        <div className="w-2 h-2 rounded-full bg-primary animate-pulse" title="Process"></div>
                        <div className="w-2 h-2 rounded-full bg-surface-container-highest" title="Upload"></div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2 text-on-surface-variant">
                        <span className="material-symbols-outlined text-sm">movie</span>
                        <span className="material-symbols-outlined text-sm">cloud_upload</span>
                      </div>
                    </td>
                    <td className="px-4 py-3"><span className="font-mono text-on-surface-variant">2m ago</span></td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button className="p-1 hover:text-primary"><span className="material-symbols-outlined text-sm">visibility</span></button>
                        <button className="p-1 hover:text-primary"><span className="material-symbols-outlined text-sm">refresh</span></button>
                      </div>
                    </td>
                  </tr>
                  {/* Row 2: Failed */}
                  <tr className="hover:bg-surface-container-high/50 transition-colors group">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-12 h-8 rounded bg-surface-container-highest overflow-hidden relative">
                          <div className="w-full h-full bg-surface-container-highest flex items-center justify-center">
                            <span className="material-symbols-outlined text-xs text-zinc-600">movie</span>
                          </div>
                        </div>
                        <div className="flex flex-col">
                          <span className="font-medium text-on-surface line-clamp-1">Tutorial_Stream_Rec.ts</span>
                          <span className="font-mono text-[9px] text-error uppercase">Status: Connection Timed Out</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-center gap-1.5">
                        <div className="w-2 h-2 rounded-full bg-error"></div>
                        <div className="w-2 h-2 rounded-full bg-surface-container-highest"></div>
                        <div className="w-2 h-2 rounded-full bg-surface-container-highest"></div>
                        <div className="w-2 h-2 rounded-full bg-surface-container-highest"></div>
                      </div>
                    </td>
                    <td className="px-4 py-3"><div className="flex gap-2 text-on-surface-variant"><span className="material-symbols-outlined text-sm">smart_display</span></div></td>
                    <td className="px-4 py-3"><span className="font-mono text-on-surface-variant">14m ago</span></td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button className="p-1 hover:text-primary"><span className="material-symbols-outlined text-sm">visibility</span></button>
                        <button className="p-1 hover:text-primary"><span className="material-symbols-outlined text-sm">refresh</span></button>
                      </div>
                    </td>
                  </tr>
                  {/* Row 3: All done */}
                  <tr className="hover:bg-surface-container-high/50 transition-colors group">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-12 h-8 rounded bg-surface-container-highest overflow-hidden relative">
                          <div className="w-full h-full bg-surface-container-highest flex items-center justify-center">
                            <span className="material-symbols-outlined text-xs text-zinc-600">movie</span>
                          </div>
                        </div>
                        <div className="flex flex-col">
                          <span className="font-medium text-on-surface line-clamp-1">Marketing_Short_A.mp4</span>
                          <span className="font-mono text-[9px] text-on-surface-variant uppercase">ID: 9022-KL</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-center gap-1.5">
                        <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                        <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                        <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                        <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                      </div>
                    </td>
                    <td className="px-4 py-3"><div className="flex gap-2 text-on-surface-variant"><span className="material-symbols-outlined text-sm">share</span><span className="material-symbols-outlined text-sm">public</span></div></td>
                    <td className="px-4 py-3"><span className="font-mono text-on-surface-variant">42m ago</span></td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button className="p-1 hover:text-primary"><span className="material-symbols-outlined text-sm">visibility</span></button>
                        <button className="p-1 hover:text-primary"><span className="material-symbols-outlined text-sm">refresh</span></button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div className="p-3 border-t border-outline-variant/10 flex justify-between items-center">
                <span className="text-[10px] font-mono text-on-surface-variant">Showing 3 of 1,284 results</span>
                <div className="flex gap-2">
                  <button className="p-1 hover:bg-surface-container-high rounded"><span className="material-symbols-outlined text-sm">chevron_left</span></button>
                  <button className="p-1 hover:bg-surface-container-high rounded"><span className="material-symbols-outlined text-sm">chevron_right</span></button>
                </div>
              </div>
            </div>
          </div>

          {/* Quick Actions (40%) */}
          <div className="lg:w-[40%] space-y-6">
            <div className="bg-surface-container-low p-5 rounded-lg space-y-4">
              <h3 className="text-xs uppercase tracking-widest font-bold text-primary">Quick Process</h3>
              <div className="space-y-2">
                <label className="text-[10px] text-on-surface-variant font-mono uppercase">Single Source URL</label>
                <div className="flex gap-2">
                  <input className="flex-1 bg-surface-container-lowest border-none rounded-md px-3 py-2 text-xs focus:ring-1 focus:ring-primary placeholder:text-zinc-600" placeholder="https://youtube.com/watch?v=..." type="text" />
                  <button className="px-4 py-2 main-button-gradient text-on-primary-fixed text-xs font-bold rounded-md">START</button>
                </div>
              </div>
            </div>
            <div className="bg-surface-container-low p-5 rounded-lg space-y-4">
              <h3 className="text-xs uppercase tracking-widest font-bold text-primary">Batch Engine</h3>
              <div className="space-y-3">
                <div className="space-y-1">
                  <label className="text-[10px] text-on-surface-variant font-mono uppercase">URL List (New line separated)</label>
                  <textarea className="w-full bg-surface-container-lowest border-none rounded-md px-3 py-2 text-xs focus:ring-1 focus:ring-primary placeholder:text-zinc-600 resize-none" placeholder="Paste multiple links here..." rows={4}></textarea>
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between text-[10px] font-mono uppercase">
                    <span className="text-on-surface-variant">Concurrency Limit</span>
                    <span className="text-primary">4 Workers</span>
                  </div>
                  <input className="w-full accent-primary h-1 bg-surface-container-lowest rounded-lg appearance-none cursor-pointer" type="range" />
                </div>
                <button className="w-full py-2 bg-surface-container-high border border-outline-variant/20 hover:border-primary/50 text-on-surface text-xs font-bold rounded-md transition-colors">INITIATE BATCH QUEUE</button>
              </div>
            </div>
            {/* Active Batch */}
            <div className="space-y-3">
              <h3 className="text-[10px] uppercase tracking-widest font-bold text-on-surface-variant px-1">Active Batch (3/12)</h3>
              <div className="space-y-2">
                <div className="bg-surface-container-lowest p-3 rounded-md border-l-2 border-primary">
                  <div className="flex justify-between items-start mb-2">
                    <span className="text-[10px] font-medium text-on-surface truncate pr-4">Social_Kit_01_Clip.mp4</span>
                    <span className="text-[10px] font-mono text-primary">82%</span>
                  </div>
                  <div className="w-full bg-surface-container-high h-1 rounded-full overflow-hidden">
                    <div className="bg-primary h-full w-[82%] transition-all duration-500"></div>
                  </div>
                </div>
                <div className="bg-surface-container-lowest p-3 rounded-md border-l-2 border-surface-container-highest">
                  <div className="flex justify-between items-start mb-2">
                    <span className="text-[10px] font-medium text-on-surface-variant truncate pr-4">Social_Kit_02_Clip.mp4</span>
                    <span className="text-[10px] font-mono text-on-surface-variant">Queued</span>
                  </div>
                  <div className="w-full bg-surface-container-high h-1 rounded-full overflow-hidden">
                    <div className="bg-surface-container-highest h-full w-0"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Activity Feed */}
        <div className="space-y-4">
          <h2 className="text-title-sm font-semibold text-on-surface">System Activity Feed</h2>
          <div className="bg-surface-container-low rounded-lg p-2 space-y-1">
            <div className="flex items-center gap-4 px-4 py-2 hover:bg-surface-container-high/40 transition-colors">
              <span className="font-mono text-[9px] text-zinc-600">14:22:01</span>
              <div className="w-1.5 h-1.5 rounded-full bg-primary/40"></div>
              <span className="text-[11px] text-on-surface"><span className="font-mono font-bold text-primary">TRANSCODER:</span> FFmpeg process initialized for <span className="text-on-surface-variant underline decoration-dotted">VID-992</span></span>
            </div>
            <div className="flex items-center gap-4 px-4 py-2 hover:bg-surface-container-high/40 transition-colors">
              <span className="font-mono text-[9px] text-zinc-600">14:19:45</span>
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500/40"></div>
              <span className="text-[11px] text-on-surface"><span className="font-mono font-bold text-emerald-500">UPLOADER:</span> Dispatch successful to <span className="font-mono bg-surface-container-highest px-1">S3_PRIMARY_BUCKET</span></span>
            </div>
            <div className="flex items-center gap-4 px-4 py-2 hover:bg-surface-container-high/40 transition-colors">
              <span className="font-mono text-[9px] text-zinc-600">14:15:22</span>
              <div className="w-1.5 h-1.5 rounded-full bg-error/40"></div>
              <span className="text-[11px] text-on-surface"><span className="font-mono font-bold text-error">CRITICAL:</span> API limit reached for Whisper V3. Rotating keys...</span>
            </div>
            <div className="flex items-center gap-4 px-4 py-2 hover:bg-surface-container-high/40 transition-colors">
              <span className="font-mono text-[9px] text-zinc-600">14:10:05</span>
              <div className="w-1.5 h-1.5 rounded-full bg-zinc-700"></div>
              <span className="text-[11px] text-on-surface-variant">System check completed. All nodes operational.</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
