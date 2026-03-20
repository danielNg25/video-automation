import { useState, useEffect, useCallback } from 'react';
import { TopBar } from '../components/TopBar';
import {
  getVideos,
  getPlatforms,
  postProcess,
  subscribeSSE,
  getProcessedVideoUrl,
} from '../api/client';
import type { VideoMetadata, PlatformSpec } from '../api/types';

const PLATFORM_INFO: Record<string, { label: string; subLangLabel: string; constraint: string }> = {
  tiktok: { label: 'TikTok', subLangLabel: 'Vietnamese', constraint: '9:16 / max 10min / 4GB' },
  youtube: { label: 'YouTube', subLangLabel: 'English', constraint: '9:16 / Shorts / 256GB' },
  facebook: { label: 'Facebook', subLangLabel: 'Vietnamese', constraint: '9:16 / max 15min / 4GB' },
  x: { label: 'X / Twitter', subLangLabel: 'English', constraint: '9:16 / max 2:20 / 512MB' },
};

const positionGrid = [
  ['top-left', 'top-center', 'top-right'],
  ['bottom-left', 'bottom-center', 'bottom-right'],
] as const;

function SubtitleProcessPage() {
  // Video selection
  const [videos, setVideos] = useState<VideoMetadata[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState('');
  const [platformSpecs, setPlatformSpecs] = useState<Record<string, PlatformSpec>>({});

  // Style editor
  const [fontName, setFontName] = useState('Arial');
  const [fontSize, setFontSize] = useState(24);
  const [outlineWidth, setOutlineWidth] = useState(2);
  const [verticalMargin, setVerticalMargin] = useState(30);
  const [shadowEnabled, setShadowEnabled] = useState(true);
  const [boldEnabled, setBoldEnabled] = useState(true);
  const [activePosition, setActivePosition] = useState('bottom-center');

  // Platform selection
  const [selectedPlatforms, setSelectedPlatforms] = useState<Record<string, boolean>>({
    tiktok: true,
    youtube: true,
    facebook: false,
    x: false,
  });

  // Processing state
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState<Record<string, { pct: number; message: string }>>({});
  const [error, setError] = useState('');
  const [completedOutputs, setCompletedOutputs] = useState<Record<string, string>>({});
  const [activeOutputTab, setActiveOutputTab] = useState('');

  // Load videos with SRT files
  const loadVideos = useCallback(async () => {
    try {
      const resp = await getVideos();
      const withSrt = resp.videos.filter((v) => v.has_srt && v.srt_languages.length > 0);
      setVideos(withSrt);
      if (withSrt.length > 0 && !selectedVideoId) {
        setSelectedVideoId(withSrt[0].video_id);
      }
    } catch {
      // API not available
    }
  }, [selectedVideoId]);

  // Load platform specs
  const loadPlatforms = useCallback(async () => {
    try {
      const specs = await getPlatforms();
      setPlatformSpecs(specs);
    } catch {
      // Use defaults
    }
  }, []);

  useEffect(() => {
    loadVideos();
    loadPlatforms();
  }, [loadVideos, loadPlatforms]);

  const selectedVideo = videos.find((v) => v.video_id === selectedVideoId);
  const activePlatforms = Object.entries(selectedPlatforms)
    .filter(([, v]) => v)
    .map(([k]) => k);

  const togglePlatform = (id: string) =>
    setSelectedPlatforms((prev) => ({ ...prev, [id]: !prev[id] }));

  const canProcess = selectedVideoId && activePlatforms.length > 0 && !isProcessing;

  // Check if a platform's required subtitle language is available
  const hasSubtitleForPlatform = (platform: string): boolean => {
    if (!selectedVideo) return false;
    const spec = platformSpecs[platform];
    const lang = spec?.subtitle_language || 'en';
    return selectedVideo.srt_languages.includes(lang);
  };

  const handleProcess = async () => {
    if (!canProcess) return;
    setIsProcessing(true);
    setError('');
    setCompletedOutputs({});

    // Init progress for each platform
    const initProgress: Record<string, { pct: number; message: string }> = {};
    for (const p of activePlatforms) {
      initProgress[p] = { pct: 0, message: 'Queued' };
    }
    setProgress(initProgress);

    try {
      const styleOverride = {
        font_name: fontName,
        font_size: fontSize,
        outline_width: outlineWidth,
        margin_v: verticalMargin,
        shadow_depth: shadowEnabled ? 1 : 0,
        bold: boldEnabled,
      };

      const { task_id } = await postProcess({
        video_id: selectedVideoId,
        platforms: activePlatforms,
        subtitle_style: styleOverride,
      });

      const es = subscribeSSE(task_id, (eventType, data) => {
        if (eventType === 'progress') {
          const platform = (data.platform as string) || '';
          const pct = data.progress as number;
          const message = data.message as string;

          if (platform && platform !== 'done') {
            setProgress((prev) => ({
              ...prev,
              [platform]: { pct: Math.round(pct * 100), message },
            }));
          }
        } else if (eventType === 'complete') {
          setIsProcessing(false);
          const outputs = (data.outputs || {}) as Record<string, string>;
          setCompletedOutputs(outputs);
          // Set all platforms to 100%
          setProgress((prev) => {
            const updated = { ...prev };
            for (const p of activePlatforms) {
              updated[p] = { pct: 100, message: 'Complete' };
            }
            return updated;
          });
          if (activePlatforms.length > 0) {
            setActiveOutputTab(activePlatforms[0]);
          }
          loadVideos();
          es.close();
        } else if (eventType === 'error') {
          setIsProcessing(false);
          setError(data.message as string);
          es.close();
        }
      });
    } catch (e) {
      setIsProcessing(false);
      setError(e instanceof Error ? e.message : 'Processing failed');
    }
  };

  // Preview style (CSS approximation)
  const previewStyle: React.CSSProperties = {
    fontFamily: fontName,
    fontSize: `${Math.max(14, fontSize * 0.7)}px`,
    fontWeight: boldEnabled ? 'bold' : 'normal',
    color: 'white',
    textShadow: shadowEnabled
      ? `0 0 ${outlineWidth}px black, 0 0 ${outlineWidth * 2}px black, 1px 1px 2px rgba(0,0,0,0.8)`
      : `0 0 ${outlineWidth}px black, 0 0 ${outlineWidth * 2}px black`,
    WebkitTextStroke: `${Math.max(0.5, outlineWidth * 0.3)}px black`,
    lineHeight: '1.4',
  };

  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar showSearch={true} searchPlaceholder="Search commands..." />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Left Panel: Subtitle Style Editor (40%) */}
          <section className="lg:w-[40%] flex flex-col gap-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-semibold tracking-tight text-on-surface">Subtitle Style Editor</h2>
              <span className="font-mono text-[10px] text-primary bg-primary/10 px-2 py-0.5 rounded">LIVE_PREVIEW</span>
            </div>

            {/* Preview Frame */}
            <div className="relative aspect-[9/16] max-h-[320px] bg-zinc-900 rounded-lg overflow-hidden border border-outline-variant/10">
              <div className="absolute inset-0 flex items-end justify-center px-4 text-center" style={{ paddingBottom: `${verticalMargin * 0.8}px` }}>
                <p style={previewStyle}>
                  This is how your subtitles will look in the final render.
                </p>
              </div>
            </div>

            {/* Editor Controls */}
            <div className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/5 space-y-5">
              {/* Font & Size */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-mono text-[10px] uppercase text-on-surface-variant">Font Family</label>
                  <select
                    value={fontName}
                    onChange={(e) => setFontName(e.target.value)}
                    className="w-full bg-surface-container-lowest border-none text-xs rounded h-9 focus:ring-1 focus:ring-primary text-on-surface"
                  >
                    <option value="Arial">Arial</option>
                    <option value="Helvetica">Helvetica</option>
                    <option value="Roboto">Roboto</option>
                    <option value="Impact">Impact</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between items-center">
                    <label className="font-mono text-[10px] uppercase text-on-surface-variant">Font Size</label>
                    <span className="font-mono text-[10px] text-primary">{fontSize}px</span>
                  </div>
                  <input
                    className="w-full accent-primary h-1.5 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                    max={36} min={16} type="range" value={fontSize}
                    onChange={(e) => setFontSize(Number(e.target.value))}
                  />
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
                  max={4} min={0} step={0.5} type="range" value={outlineWidth}
                  onChange={(e) => setOutlineWidth(Number(e.target.value))}
                />
              </div>

              {/* Toggles */}
              <div className="flex items-center gap-6">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShadowEnabled(!shadowEnabled)}
                    className={`w-8 h-4 rounded-full relative cursor-pointer ${shadowEnabled ? 'bg-primary' : 'bg-surface-container-highest'}`}
                  >
                    <div className={`absolute top-0.5 w-3 h-3 bg-on-primary-fixed rounded-full transition-all ${shadowEnabled ? 'right-0.5' : 'left-0.5'}`} />
                  </button>
                  <span className="font-mono text-[10px] uppercase text-on-surface">Shadow</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setBoldEnabled(!boldEnabled)}
                    className={`w-8 h-4 rounded-full relative cursor-pointer ${boldEnabled ? 'bg-primary' : 'bg-surface-container-highest'}`}
                  >
                    <div className={`absolute top-0.5 w-3 h-3 bg-on-primary-fixed rounded-full transition-all ${boldEnabled ? 'right-0.5' : 'left-0.5'}`} />
                  </button>
                  <span className="font-mono text-[10px] uppercase text-on-surface">Bold</span>
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
                  <div className="flex justify-between items-center">
                    <label className="font-mono text-[10px] uppercase text-on-surface-variant">Vertical Margin</label>
                    <span className="font-mono text-[10px] text-primary">{verticalMargin}px</span>
                  </div>
                  <input
                    className="w-full accent-primary h-1.5 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                    max={100} min={20} type="range" value={verticalMargin}
                    onChange={(e) => setVerticalMargin(Number(e.target.value))}
                  />
                </div>
              </div>
            </div>
          </section>

          {/* Right Panel: Processing Controls (60%) */}
          <section className="lg:w-[60%] flex flex-col gap-6">
            <div className="bg-surface-container-low p-6 rounded-xl border border-outline-variant/5">
              <h2 className="text-lg font-semibold tracking-tight text-on-surface mb-6">Processing Configuration</h2>
              <div className="space-y-6">
                {/* Video Selector */}
                <div className="space-y-2">
                  <label className="font-mono text-[10px] uppercase text-on-surface-variant">Source Video</label>
                  <div className="relative">
                    <select
                      value={selectedVideoId}
                      onChange={(e) => setSelectedVideoId(e.target.value)}
                      className="w-full bg-surface-container-lowest border-none text-sm rounded-lg h-12 pl-4 pr-10 focus:ring-1 focus:ring-primary text-on-surface appearance-none"
                    >
                      {videos.length === 0 && <option value="">No videos with subtitles</option>}
                      {videos.map((v) => (
                        <option key={v.video_id} value={v.video_id}>
                          {v.title || v.video_id} ({v.size}) — SRT: {v.srt_languages.join(', ')}
                        </option>
                      ))}
                    </select>
                    <span className="material-symbols-outlined absolute right-4 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none">unfold_more</span>
                  </div>
                  {selectedVideo && (
                    <div className="flex gap-2 mt-1">
                      {selectedVideo.srt_languages.map((lang) => (
                        <span key={lang} className="font-mono text-[9px] px-1.5 py-0.5 bg-primary/20 text-primary rounded uppercase">
                          {lang}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Platform Selector */}
                <div className="space-y-3">
                  <label className="font-mono text-[10px] uppercase text-on-surface-variant">Target Platforms</label>
                  <div className="space-y-2">
                    {Object.entries(PLATFORM_INFO).map(([id, info]) => {
                      const spec = platformSpecs[id];
                      const subLang = spec?.subtitle_language || (id === 'tiktok' || id === 'facebook' ? 'vi' : 'en');
                      const hasSub = hasSubtitleForPlatform(id);

                      return (
                        <div
                          key={id}
                          className={`p-3 rounded-lg bg-surface-container-lowest border ${
                            selectedPlatforms[id] ? 'border-primary/30' : 'border-outline-variant/10'
                          } flex items-start gap-3 cursor-pointer hover:border-primary/40 transition-colors`}
                          onClick={() => togglePlatform(id)}
                        >
                          <input
                            checked={selectedPlatforms[id] || false}
                            onChange={() => togglePlatform(id)}
                            className="mt-1 rounded border-outline-variant bg-surface-container text-primary focus:ring-primary w-4 h-4"
                            type="checkbox"
                          />
                          <div className="flex-1">
                            <div className="flex justify-between items-center mb-1">
                              <span className="text-sm font-medium">{info.label}</span>
                              <div className="flex gap-1.5">
                                <span className="font-mono text-[9px] px-1.5 py-0.5 bg-primary/20 text-primary rounded uppercase">
                                  {subLang} subs
                                </span>
                                <span className="font-mono text-[9px] px-1.5 py-0.5 bg-zinc-800 text-zinc-400 rounded">
                                  {info.constraint}
                                </span>
                              </div>
                            </div>
                            {!hasSub && selectedVideo && (
                              <p className="text-[10px] text-amber-400 flex items-center gap-1">
                                <span className="material-symbols-outlined text-[12px]">warning</span>
                                {subLang.toUpperCase()} SRT not found — will use fallback
                              </p>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Process Button */}
                <button
                  disabled={!canProcess}
                  onClick={handleProcess}
                  className={`w-full h-12 font-bold rounded-lg flex items-center justify-center gap-2 transition-all ${
                    canProcess
                      ? 'bg-gradient-to-r from-primary to-primary-container text-on-primary-fixed hover:shadow-[0_0_20px_rgba(160,120,255,0.3)]'
                      : 'bg-surface-container-highest text-on-surface-variant cursor-not-allowed'
                  }`}
                >
                  {isProcessing ? (
                    <>
                      <span className="material-symbols-outlined animate-spin text-lg">progress_activity</span>
                      PROCESSING...
                    </>
                  ) : (
                    <>
                      <span className="material-symbols-outlined">auto_fix_high</span>
                      PROCESS VIDEO
                    </>
                  )}
                </button>

                {error && (
                  <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                    {error}
                  </div>
                )}
              </div>
            </div>

            {/* Processing Progress */}
            {(isProcessing || Object.keys(completedOutputs).length > 0) && (
              <div className="bg-surface-container-low rounded-xl border border-outline-variant/5 overflow-hidden">
                {/* Progress Bars */}
                {Object.keys(progress).length > 0 && (
                  <div className="p-6 space-y-4">
                    <h3 className="font-mono text-[10px] uppercase text-on-surface-variant">Processing Progress</h3>
                    {Object.entries(progress).map(([platform, { pct, message }]) => (
                      <div key={platform} className="space-y-1.5">
                        <div className="flex justify-between items-center">
                          <div className="flex items-center gap-2">
                            <span className={`w-2 h-2 rounded-full ${
                              pct >= 100 ? 'bg-emerald-500' : pct > 0 ? 'bg-primary animate-pulse' : 'bg-zinc-600'
                            }`} />
                            <span className="text-xs font-medium">
                              {PLATFORM_INFO[platform]?.label || platform}
                            </span>
                            <span className="font-mono text-[9px] text-on-surface-variant">
                              {platformSpecs[platform]?.subtitle_language?.toUpperCase() || ''}
                            </span>
                          </div>
                          <span className={`font-mono text-xs ${pct >= 100 ? 'text-emerald-500' : 'text-primary'}`}>
                            {pct}%
                          </span>
                        </div>
                        <div className="h-1 bg-surface-container-highest rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-300 ${
                              pct >= 100 ? 'bg-emerald-500' : 'bg-primary shadow-[0_0_10px_rgba(208,188,255,0.5)]'
                            }`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <p className="font-mono text-[9px] text-on-surface-variant">{message}</p>
                      </div>
                    ))}
                  </div>
                )}

                {/* Output Preview */}
                {Object.keys(completedOutputs).length > 0 && (
                  <div className="border-t border-outline-variant/10">
                    <div className="flex px-6 pt-4 gap-2">
                      {Object.keys(completedOutputs).map((platform) => (
                        <button
                          key={platform}
                          onClick={() => setActiveOutputTab(platform)}
                          className={`text-xs font-medium px-3 py-1.5 rounded-t ${
                            activeOutputTab === platform
                              ? 'bg-surface-container-highest text-primary'
                              : 'text-on-surface-variant hover:text-on-surface'
                          }`}
                        >
                          {PLATFORM_INFO[platform]?.label || platform} ({platformSpecs[platform]?.subtitle_language || '?'})
                        </button>
                      ))}
                    </div>
                    {activeOutputTab && (
                      <div className="p-6 pt-3">
                        <video
                          controls
                          className="w-full max-h-[400px] rounded-lg bg-black"
                          src={getProcessedVideoUrl(selectedVideoId, activeOutputTab)}
                        >
                          Your browser does not support the video tag.
                        </video>
                        <p className="font-mono text-[9px] text-on-surface-variant mt-2">
                          {selectedVideoId}_{activeOutputTab}.mp4
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

export default SubtitleProcessPage;
