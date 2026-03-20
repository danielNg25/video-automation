import { useState } from 'react';
import { TopBar } from '../components/TopBar';

const positionGrid = [
  ['top-left', 'top-center', 'top-right'],
  ['bottom-left', 'bottom-center', 'bottom-right'],
] as const;

function SubtitleProcessPage() {
  const [fontSize, setFontSize] = useState(24);
  const [outlineWidth, setOutlineWidth] = useState(1.5);
  const [verticalMargin, setVerticalMargin] = useState(8);
  const [shadowEnabled, setShadowEnabled] = useState(true);
  const [boldEnabled, setBoldEnabled] = useState(true);
  const [activePosition, setActivePosition] = useState('bottom-center');
  const [activeTab, setActiveTab] = useState<'queue' | 'results' | 'logs'>('queue');
  const [selectedLanguages, setSelectedLanguages] = useState<Record<string, boolean>>({
    'English (Auto)': true,
    'Spanish (ES)': false,
    'French (FR)': false,
    'German (DE)': false,
  });
  const [selectedPlatforms, setSelectedPlatforms] = useState<Record<string, boolean>>({
    tiktok: true,
    youtube: true,
    facebook: false,
    twitter: false,
  });

  const toggleLanguage = (label: string) =>
    setSelectedLanguages((prev) => ({ ...prev, [label]: !prev[label] }));
  const togglePlatform = (id: string) =>
    setSelectedPlatforms((prev) => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar showSearch={true} searchPlaceholder="Search commands..." />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="flex flex-col lg:flex-row gap-6 h-full">
          {/* Left Panel: Subtitle Style Editor (40%) */}
          <section className="lg:w-[40%] flex flex-col gap-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-semibold tracking-tight text-on-surface">Subtitle Style Editor</h2>
              <span className="font-mono text-[10px] text-primary bg-primary/10 px-2 py-0.5 rounded">LIVE_PREVIEW</span>
            </div>
            {/* Preview Frame */}
            <div className="relative aspect-video bg-surface-container-lowest rounded-lg overflow-hidden border border-outline-variant/10 group">
              <div className="w-full h-full bg-surface-container-lowest"></div>
              <div className="absolute inset-0 flex items-end justify-center pb-8 px-4 text-center">
                <p className="text-2xl font-bold text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)] leading-tight">
                  This is how your subtitles will appear in the final render.
                </p>
              </div>
              <div className="absolute top-2 right-2 flex gap-2">
                <button className="bg-surface-container-highest/80 backdrop-blur-md p-1.5 rounded-md hover:bg-surface-container-highest">
                  <span className="material-symbols-outlined text-sm">fullscreen</span>
                </button>
              </div>
            </div>
            {/* Editor Controls */}
            <div className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/5 space-y-6">
              {/* Font & Size */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-mono text-[10px] uppercase text-on-surface-variant">Font Family</label>
                  <select className="w-full bg-surface-container-lowest border-none text-xs rounded h-9 focus:ring-1 focus:ring-primary text-on-surface">
                    <option>Inter Display</option>
                    <option>JetBrains Mono</option>
                    <option>Roboto Condensed</option>
                    <option>Impact Heavy</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between items-center">
                    <label className="font-mono text-[10px] uppercase text-on-surface-variant">Font Size</label>
                    <span className="font-mono text-[10px] text-primary">{fontSize}px</span>
                  </div>
                  <input
                    className="w-full accent-primary h-1.5 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                    max={36}
                    min={16}
                    type="range"
                    value={fontSize}
                    onChange={(e) => setFontSize(Number(e.target.value))}
                  />
                </div>
              </div>
              {/* Color Pickers */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-mono text-[10px] uppercase text-on-surface-variant">Text Color</label>
                  <div className="flex items-center gap-2 bg-surface-container-lowest p-1.5 rounded border border-outline-variant/10">
                    <div className="w-6 h-6 rounded bg-white border border-outline-variant/20"></div>
                    <span className="font-mono text-[10px]">#FFFFFF</span>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <label className="font-mono text-[10px] uppercase text-on-surface-variant">Outline Color</label>
                  <div className="flex items-center gap-2 bg-surface-container-lowest p-1.5 rounded border border-outline-variant/10">
                    <div className="w-6 h-6 rounded bg-black border border-outline-variant/20"></div>
                    <span className="font-mono text-[10px]">#000000</span>
                  </div>
                </div>
              </div>
              {/* Outline Width */}
              <div className="space-y-1.5">
                <div className="flex justify-between items-center">
                  <label className="font-mono text-[10px] uppercase text-on-surface-variant">Outline Width</label>
                  <span className="font-mono text-[10px] text-primary">{outlineWidth}px</span>
                </div>
                <input
                  className="w-full accent-primary h-1.5 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                  max={5}
                  min={0}
                  step={0.5}
                  type="range"
                  value={outlineWidth}
                  onChange={(e) => setOutlineWidth(Number(e.target.value))}
                />
              </div>
              {/* Shadow/Bold Toggles */}
              <div className="flex items-center justify-between pt-2">
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setShadowEnabled(!shadowEnabled)}
                      className={`w-8 h-4 rounded-full relative cursor-pointer ${shadowEnabled ? 'bg-primary' : 'bg-surface-container-highest'}`}
                    >
                      <div className={`absolute top-0.5 w-3 h-3 bg-on-primary-fixed rounded-full transition-all ${shadowEnabled ? 'right-0.5' : 'left-0.5'}`}></div>
                    </button>
                    <span className="font-mono text-[10px] uppercase text-on-surface">Shadow</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setBoldEnabled(!boldEnabled)}
                      className={`w-8 h-4 rounded-full relative cursor-pointer ${boldEnabled ? 'bg-primary' : 'bg-surface-container-highest'}`}
                    >
                      <div className={`absolute top-0.5 w-3 h-3 bg-on-primary-fixed rounded-full transition-all ${boldEnabled ? 'right-0.5' : 'left-0.5'}`}></div>
                    </button>
                    <span className="font-mono text-[10px] uppercase text-on-surface">Bold</span>
                  </div>
                </div>
              </div>
              {/* Position + Vertical Margin */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-mono text-[10px] uppercase text-on-surface-variant">Position</label>
                  <div className="grid grid-cols-3 gap-1 p-1 bg-surface-container-lowest rounded">
                    {positionGrid.flat().map((pos) => (
                      <button
                        key={pos}
                        onClick={() => setActivePosition(pos)}
                        className={`aspect-square rounded-sm ${
                          activePosition === pos
                            ? 'bg-primary/40 border border-primary/60'
                            : 'bg-surface-container-highest/20'
                        }`}
                      />
                    ))}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <label className="font-mono text-[10px] uppercase text-on-surface-variant">Vertical Margin</label>
                  <div className="flex flex-col gap-2">
                    <span className="font-mono text-[10px] text-right text-primary">{verticalMargin}%</span>
                    <input
                      className="w-full accent-primary h-1.5 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                      max={50}
                      min={0}
                      type="range"
                      value={verticalMargin}
                      onChange={(e) => setVerticalMargin(Number(e.target.value))}
                    />
                  </div>
                </div>
              </div>
            </div>
          </section>
          {/* Right Panel: Processing Controls (60%) */}
          <section className="lg:w-[60%] flex flex-col gap-6">
            <div className="bg-surface-container-low p-6 rounded-xl border border-outline-variant/5">
              <h2 className="text-lg font-semibold tracking-tight text-on-surface mb-6">Processing Configuration</h2>
              <div className="space-y-6">
                <div className="space-y-2">
                  <label className="font-mono text-[10px] uppercase text-on-surface-variant">Source Video</label>
                  <div className="relative">
                    <select className="w-full bg-surface-container-lowest border-none text-sm rounded-lg h-12 pl-4 pr-10 focus:ring-1 focus:ring-primary text-on-surface appearance-none">
                      <option>Interview_Final_Render_v2.mp4 (142MB)</option>
                    </select>
                    <span className="material-symbols-outlined absolute right-4 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none">unfold_more</span>
                  </div>
                </div>
                <div className="grid md:grid-cols-2 gap-8">
                  {/* Languages */}
                  <div className="space-y-4">
                    <label className="font-mono text-[10px] uppercase text-on-surface-variant">Output Languages</label>
                    <div className="space-y-2 max-h-48 overflow-y-auto pr-2">
                      {Object.entries(selectedLanguages).map(([label, checked]) => (
                        <label
                          key={label}
                          className="flex items-center justify-between p-3 rounded-lg bg-surface-container-lowest border border-outline-variant/10 cursor-pointer hover:border-primary/40 transition-colors"
                        >
                          <span className="text-sm">{label}</span>
                          <input
                            checked={checked}
                            onChange={() => toggleLanguage(label)}
                            className="rounded border-outline-variant bg-surface-container text-primary focus:ring-primary w-4 h-4"
                            type="checkbox"
                          />
                        </label>
                      ))}
                    </div>
                  </div>
                  {/* Platforms */}
                  <div className="space-y-4">
                    <label className="font-mono text-[10px] uppercase text-on-surface-variant">Platform Optimization</label>
                    <div className="space-y-2">
                      <div className={`p-3 rounded-lg bg-surface-container-lowest border ${selectedPlatforms.tiktok ? 'border-primary/30' : 'border-outline-variant/10'} flex items-start gap-3`}>
                        <input
                          checked={selectedPlatforms.tiktok}
                          onChange={() => togglePlatform('tiktok')}
                          className="mt-1 rounded border-outline-variant bg-surface-container text-primary focus:ring-primary w-4 h-4"
                          type="checkbox"
                        />
                        <div className="flex-1">
                          <div className="flex justify-between items-center mb-1">
                            <span className="text-sm font-medium">TikTok</span>
                            <span className="font-mono text-[9px] px-1.5 py-0.5 bg-primary/20 text-primary rounded">9:16</span>
                          </div>
                          <p className="text-[10px] text-on-surface-variant">Max 10min / Vertical Burn-in</p>
                        </div>
                      </div>
                      <div className="p-3 rounded-lg bg-surface-container-lowest border border-outline-variant/10 flex items-start gap-3 hover:border-primary/40 transition-colors cursor-pointer">
                        <input
                          checked={selectedPlatforms.youtube}
                          onChange={() => togglePlatform('youtube')}
                          className="mt-1 rounded border-outline-variant bg-surface-container text-primary focus:ring-primary w-4 h-4"
                          type="checkbox"
                        />
                        <div className="flex-1">
                          <div className="flex justify-between items-center mb-1">
                            <span className="text-sm font-medium">YouTube</span>
                            <span className="font-mono text-[9px] px-1.5 py-0.5 bg-zinc-800 text-zinc-400 rounded">MAX 60s</span>
                          </div>
                          <p className="text-[10px] text-on-surface-variant">Shorts optimization enabled</p>
                        </div>
                      </div>
                      <div className="p-3 rounded-lg bg-surface-container-lowest border border-outline-variant/10 flex items-start gap-3 hover:border-primary/40 transition-colors cursor-pointer">
                        <input
                          checked={selectedPlatforms.facebook}
                          onChange={() => togglePlatform('facebook')}
                          className="mt-1 rounded border-outline-variant bg-surface-container text-primary focus:ring-primary w-4 h-4"
                          type="checkbox"
                        />
                        <div className="flex-1">
                          <div className="flex justify-between items-center mb-1">
                            <span className="text-sm font-medium">Facebook</span>
                            <span className="font-mono text-[9px] px-1.5 py-0.5 bg-zinc-800 text-zinc-400 rounded">15:00</span>
                          </div>
                          <p className="text-[10px] text-on-surface-variant">Standard 16:9 Letterbox</p>
                        </div>
                      </div>
                      <div className="p-3 rounded-lg bg-surface-container-lowest border border-outline-variant/10 flex items-start gap-3 hover:border-primary/40 transition-colors cursor-pointer">
                        <input
                          checked={selectedPlatforms.twitter}
                          onChange={() => togglePlatform('twitter')}
                          className="mt-1 rounded border-outline-variant bg-surface-container text-primary focus:ring-primary w-4 h-4"
                          type="checkbox"
                        />
                        <div className="flex-1">
                          <div className="flex justify-between items-center mb-1">
                            <span className="text-sm font-medium">X / Twitter</span>
                            <span className="font-mono text-[9px] px-1.5 py-0.5 bg-zinc-800 text-zinc-400 rounded">2:20</span>
                          </div>
                          <p className="text-[10px] text-on-surface-variant">High-bitrate processing</p>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <button className="w-full h-12 bg-gradient-to-r from-primary to-primary-container text-on-primary-fixed font-bold rounded-lg flex items-center justify-center gap-2 hover:shadow-[0_0_20px_rgba(160,120,255,0.3)] transition-all">
                  <span className="material-symbols-outlined">auto_fix_high</span>
                  PROCESS VIDEO ASSETS
                </button>
              </div>
            </div>
            {/* Processing Queue */}
            <div className="flex-1 bg-surface-container-low rounded-xl border border-outline-variant/5 flex flex-col overflow-hidden">
              <div className="flex items-center px-6 py-4 border-b border-outline-variant/10">
                <nav className="flex gap-6">
                  <button
                    onClick={() => setActiveTab('queue')}
                    className={`text-xs font-bold pb-4 ${activeTab === 'queue' ? 'border-b-2 border-primary text-primary' : 'text-on-surface-variant hover:text-on-surface'}`}
                  >
                    PROCESSING QUEUE
                  </button>
                  <button
                    onClick={() => setActiveTab('results')}
                    className={`text-xs font-medium pb-4 ${activeTab === 'results' ? 'border-b-2 border-primary text-primary' : 'text-on-surface-variant hover:text-on-surface'}`}
                  >
                    RESULTS
                  </button>
                  <button
                    onClick={() => setActiveTab('logs')}
                    className={`text-xs font-medium pb-4 ${activeTab === 'logs' ? 'border-b-2 border-primary text-primary' : 'text-on-surface-variant hover:text-on-surface'}`}
                  >
                    EXPORT LOGS
                  </button>
                </nav>
              </div>
              <div className="p-6 space-y-4 overflow-y-auto">
                {activeTab === 'queue' && (
                  <>
                    <div className="space-y-2">
                      <div className="flex justify-between items-end">
                        <div>
                          <h4 className="text-xs font-bold flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-primary animate-pulse"></span>
                            TikTok_Interview_v2.mp4
                          </h4>
                          <p className="font-mono text-[9px] text-on-surface-variant mt-1">ENCODING_VO_STREAMS &bull; 42.1MB / 142MB</p>
                        </div>
                        <span className="font-mono text-xs text-primary">32%</span>
                      </div>
                      <div className="h-1 bg-surface-container-highest rounded-full overflow-hidden">
                        <div className="h-full bg-primary w-[32%] rounded-full shadow-[0_0_10px_rgba(208,188,255,0.5)]"></div>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className="flex justify-between items-end">
                        <div>
                          <h4 className="text-xs font-bold flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-zinc-600"></span>
                            YT_Shorts_Process_01.mp4
                          </h4>
                          <p className="font-mono text-[9px] text-on-surface-variant mt-1">QUEUED &bull; WAITING FOR RESOURCES</p>
                        </div>
                        <span className="font-mono text-xs text-zinc-500">0%</span>
                      </div>
                      <div className="h-1 bg-surface-container-highest rounded-full overflow-hidden">
                        <div className="h-full bg-primary w-0 rounded-full"></div>
                      </div>
                    </div>
                    {/* Finished preview */}
                    <div className="mt-6 p-4 rounded-lg bg-surface-container-lowest border border-outline-variant/10 group cursor-pointer hover:bg-surface-container-highest transition-colors">
                      <div className="flex items-center gap-4">
                        <div className="w-20 aspect-video rounded bg-zinc-800 overflow-hidden relative">
                          <div className="w-full h-full bg-surface-container-highest"></div>
                          <div className="absolute inset-0 flex items-center justify-center bg-black/40">
                            <span className="material-symbols-outlined text-white text-lg">play_arrow</span>
                          </div>
                        </div>
                        <div className="flex-1">
                          <div className="flex justify-between">
                            <span className="text-xs font-bold">Latest Result: Facebook_Master_03.mp4</span>
                            <span className="material-symbols-outlined text-emerald-500 text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                          </div>
                          <div className="flex gap-2 mt-1">
                            <span className="font-mono text-[9px] text-zinc-500">1080p</span>
                            <span className="font-mono text-[9px] text-zinc-500">24fps</span>
                            <span className="font-mono text-[9px] text-zinc-500">AAC_AUDIO</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </>
                )}
                {activeTab === 'results' && (
                  <p className="text-sm text-on-surface-variant text-center py-8">No results yet.</p>
                )}
                {activeTab === 'logs' && (
                  <p className="text-sm text-on-surface-variant text-center py-8">No export logs available.</p>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>
      {/* Footer */}
      <footer className="h-10 border-t border-outline-variant/5 bg-surface-container-lowest px-6 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
            <span className="font-mono text-[10px] uppercase text-zinc-500">Engine Stable</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase text-zinc-500">GPU Load:</span>
            <span className="font-mono text-[10px] text-primary">14.2%</span>
          </div>
        </div>
        <div className="flex items-center gap-2 font-mono text-[10px] text-zinc-600 uppercase">
          Precision Video SDK v2.4.1-stable
        </div>
      </footer>
    </div>
  );
}

export default SubtitleProcessPage;
