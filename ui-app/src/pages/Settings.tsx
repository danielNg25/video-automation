import { useState } from 'react';
import { TopBar } from '../components/TopBar';

function SettingsPage() {
  const [activeSection, setActiveSection] = useState('douyin');
  const [vadFilter, setVadFilter] = useState(true);
  const [crfValue, setCrfValue] = useState(23);
  const [skipExisting, setSkipExisting] = useState(true);

  const scrollToSection = (id: string) => {
    setActiveSection(id);
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
  };

  const sidebarItems = [
    { id: 'douyin', icon: 'api', label: 'Douyin API' },
    { id: 'transcription', icon: 'description', label: 'Transcription' },
    { id: 'video', icon: 'movie_filter', label: 'Video Processing' },
    { id: 'platforms', icon: 'hub', label: 'Platforms' },
    { id: 'pipeline', icon: 'account_tree', label: 'Pipeline' },
  ];

  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar title="VideoPrecision" showSearch={true} searchPlaceholder="Search settings..." />

      {/* Settings Workspace */}
      <div className="flex flex-1 overflow-hidden">
        {/* Settings Sidebar (Sub-nav) */}
        <nav className="w-56 bg-surface-container-lowest flex flex-col p-2 gap-1 border-r border-zinc-800/10">
          {sidebarItems.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              onClick={(e) => {
                e.preventDefault();
                scrollToSection(item.id);
              }}
              className={`flex items-center gap-3 px-4 py-2.5 rounded text-sm font-medium transition-colors ${
                activeSection === item.id
                  ? 'bg-surface-container-high text-primary'
                  : 'text-zinc-400 hover:bg-surface-container-low'
              }`}
            >
              <span className="material-symbols-outlined text-[18px]">{item.icon}</span>
              {item.label}
            </a>
          ))}
        </nav>

        {/* Settings Content */}
        <div className="flex-1 overflow-y-auto p-8">
          <div className="max-w-4xl mx-auto space-y-12 pb-24">
            {/* Douyin API */}
            <section className="space-y-6" id="douyin">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">Douyin API</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">Configuration for local scraper and signature services.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Service URL</label>
                  <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono text-primary" type="text" defaultValue="http://localhost:8080/api/v1" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Cookie Path</label>
                  <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="text" defaultValue="./auth/douyin.cookies" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Request Timeout (ms)</label>
                  <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="number" defaultValue={30000} />
                </div>
                <div className="flex items-end pb-1">
                  <button className="flex items-center gap-2 px-4 py-3 bg-surface-container-high hover:bg-surface-variant rounded text-xs font-bold uppercase tracking-widest transition-colors w-full justify-center">
                    <span className="material-symbols-outlined text-emerald-500" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                    Docker Status: Healthy
                  </button>
                </div>
              </div>
            </section>

            {/* Transcription */}
            <section className="space-y-6" id="transcription">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">Transcription</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">Whisper engine and VAD parameters.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Model Size</label>
                  <select className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm" defaultValue="large-v3">
                    <option>tiny</option>
                    <option>base</option>
                    <option>small</option>
                    <option>medium</option>
                    <option value="large-v3">large-v3</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Device</label>
                  <select className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" defaultValue="cuda:0">
                    <option>cpu</option>
                    <option value="cuda:0">cuda:0</option>
                    <option value="cuda:1">cuda:1</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Compute Type</label>
                  <select className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" defaultValue="float16">
                    <option value="float16">float16</option>
                    <option value="int8_float16">int8_float16</option>
                    <option value="int8">int8</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Language</label>
                  <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm" placeholder="Auto (detect)" type="text" />
                </div>
                <div className="flex items-center justify-between p-3 bg-surface-container-low rounded">
                  <span className="text-xs font-bold uppercase tracking-widest text-zinc-400">VAD Filter</span>
                  <div className="relative inline-flex items-center cursor-pointer">
                    <input
                      checked={vadFilter}
                      onChange={(e) => setVadFilter(e.target.checked)}
                      className="sr-only peer"
                      type="checkbox"
                    />
                    <div className="w-9 h-5 bg-surface-container-highest peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-primary"></div>
                  </div>
                </div>
                <div className="flex items-center justify-between p-3 bg-surface-container-low rounded">
                  <span className="text-xs font-bold uppercase tracking-widest text-zinc-400">Models</span>
                  <span className="text-[10px] font-mono bg-emerald-900/30 text-emerald-400 px-2 py-0.5 rounded">DOWNLOADED</span>
                </div>
              </div>
            </section>

            {/* Video Processing */}
            <section className="space-y-6" id="video">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">Video Processing</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">FFmpeg encoding and rendering defaults.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8 bg-surface-container-low/50 p-6 rounded-lg">
                <div className="space-y-4">
                  <div className="flex justify-between items-center">
                    <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">CRF (Quality)</label>
                    <span className="text-xs font-mono text-primary">{crfValue}</span>
                  </div>
                  <input
                    className="w-full h-1.5 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                    max={51}
                    min={0}
                    type="range"
                    value={crfValue}
                    onChange={(e) => setCrfValue(Number(e.target.value))}
                  />
                  <div className="flex justify-between text-[10px] font-mono text-zinc-600">
                    <span>LOSSLESS (0)</span>
                    <span>LOW QUAL (51)</span>
                  </div>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Preset</label>
                  <select className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" defaultValue="medium">
                    <option>ultrafast</option>
                    <option>superfast</option>
                    <option>veryfast</option>
                    <option>faster</option>
                    <option value="medium">medium</option>
                    <option>slow</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Audio Bitrate</label>
                  <div className="flex items-center">
                    <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded-l p-3 text-sm font-mono" type="text" defaultValue="192" />
                    <span className="bg-surface-container-highest px-4 py-3 border-y border-r border-outline-variant/20 text-xs font-mono text-zinc-500 rounded-r">kbps</span>
                  </div>
                </div>
              </div>
            </section>

            {/* Platforms */}
            <section className="space-y-6" id="platforms">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">Platforms</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">Destination specific publishing settings.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* YouTube */}
                <div className="bg-surface-container-low p-5 rounded border border-zinc-800/10">
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded bg-red-900/20 flex items-center justify-center">
                        <span className="material-symbols-outlined text-red-500 text-sm">play_circle</span>
                      </div>
                      <span className="text-sm font-bold uppercase tracking-tight">YouTube</span>
                    </div>
                    <input defaultChecked className="w-4 h-4 text-primary bg-zinc-800 border-zinc-700 rounded focus:ring-0" type="checkbox" />
                  </div>
                  <div className="space-y-3">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block">Default Privacy</label>
                    <select className="w-full bg-surface-container-lowest border border-outline-variant/20 text-xs py-2 px-3 rounded" defaultValue="Private">
                      <option>Public</option>
                      <option value="Private">Private</option>
                      <option>Unlisted</option>
                    </select>
                  </div>
                </div>

                {/* TikTok */}
                <div className="bg-surface-container-low p-5 rounded border border-zinc-800/10">
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded bg-cyan-900/20 flex items-center justify-center">
                        <span className="material-symbols-outlined text-cyan-400 text-sm">music_note</span>
                      </div>
                      <span className="text-sm font-bold uppercase tracking-tight">TikTok</span>
                    </div>
                    <input defaultChecked className="w-4 h-4 text-primary bg-zinc-800 border-zinc-700 rounded focus:ring-0" type="checkbox" />
                  </div>
                  <div className="space-y-3">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block">Upload Mode</label>
                    <select className="w-full bg-surface-container-lowest border border-outline-variant/20 text-xs py-2 px-3 rounded" defaultValue="API Direct">
                      <option value="API Direct">API Direct</option>
                      <option>Cookie Browser</option>
                    </select>
                  </div>
                </div>

                {/* Facebook */}
                <div className="bg-surface-container-low p-5 rounded border border-zinc-800/10">
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded bg-blue-900/20 flex items-center justify-center">
                        <span className="material-symbols-outlined text-blue-500 text-sm">groups</span>
                      </div>
                      <span className="text-sm font-bold uppercase tracking-tight">Facebook</span>
                    </div>
                    <input className="w-4 h-4 text-primary bg-zinc-800 border-zinc-700 rounded focus:ring-0" type="checkbox" />
                  </div>
                  <div className="space-y-3">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block">Target Type</label>
                    <select className="w-full bg-surface-container-lowest border border-outline-variant/20 text-xs py-2 px-3 rounded" defaultValue="Page Reels">
                      <option value="Page Reels">Page Reels</option>
                      <option>Personal Feed</option>
                    </select>
                  </div>
                </div>

                {/* X (Twitter) */}
                <div className="bg-surface-container-low p-5 rounded border border-zinc-800/10">
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded bg-zinc-900 flex items-center justify-center">
                        <span className="material-symbols-outlined text-zinc-100 text-sm">close</span>
                      </div>
                      <span className="text-sm font-bold uppercase tracking-tight">X (Twitter)</span>
                    </div>
                    <input className="w-4 h-4 text-primary bg-zinc-800 border-zinc-700 rounded focus:ring-0" type="checkbox" />
                  </div>
                  <div className="space-y-3">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 block">Automation Note</label>
                    <p className="text-[11px] text-zinc-500 italic">API integration requires Premium tier client ID.</p>
                  </div>
                </div>
              </div>
            </section>

            {/* Pipeline */}
            <section className="space-y-6" id="pipeline">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">Pipeline</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">Batch processing and concurrency management.</p>
              </div>
              <div className="space-y-6">
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Global Data Path</label>
                  <div className="flex gap-2">
                    <input className="flex-1 bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="text" defaultValue="/mnt/storage/video_precision/data" />
                    <button className="px-4 py-2 bg-surface-container-high hover:bg-surface-variant transition-colors rounded">
                      <span className="material-symbols-outlined text-zinc-400">folder_open</span>
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Max Concurrent</label>
                    <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="number" defaultValue={3} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Retry Attempts</label>
                    <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="number" defaultValue={3} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Retry Delay (s)</label>
                    <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="number" defaultValue={10} />
                  </div>
                </div>
                <div className="flex items-center justify-between p-4 bg-primary-container/10 rounded-lg border border-primary/20">
                  <div>
                    <h4 className="text-sm font-semibold text-primary">Skip Existing Files</h4>
                    <p className="text-[11px] text-zinc-500 mt-0.5">Resume tasks by checking for output fingerprints before starting compute.</p>
                  </div>
                  <div className="relative inline-flex items-center cursor-pointer">
                    <input
                      checked={skipExisting}
                      onChange={(e) => setSkipExisting(e.target.checked)}
                      className="sr-only peer"
                      type="checkbox"
                    />
                    <div className="w-11 h-6 bg-surface-container-highest peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>

      {/* Sticky Footer */}
      <div className="absolute bottom-0 left-0 right-0 bg-surface/80 backdrop-blur-md border-t border-zinc-800/30 px-8 py-4 flex justify-between items-center z-50">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-emerald-500 text-sm">cloud_done</span>
          <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-widest">All local changes are cached</span>
        </div>
        <div className="flex gap-4">
          <button className="px-6 py-2 rounded text-xs font-bold uppercase tracking-widest text-zinc-400 hover:text-on-surface transition-colors">Discard</button>
          <button className="px-8 py-2.5 bg-gradient-to-br from-primary to-primary-container text-on-primary-fixed font-bold text-xs uppercase tracking-widest rounded shadow-lg shadow-primary/20 active:scale-95 transition-all">
            Save Changes
          </button>
        </div>
      </div>
    </div>
  );
}

export default SettingsPage;
