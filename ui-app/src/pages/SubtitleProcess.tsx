import { useState, useEffect, useCallback } from 'react';
import { TopBar } from '../components/TopBar';
import {
  getVideos,
  getPlatforms,
  postProcess,
  getTTSPlatforms,
  subscribeSSE,
  getProcessedVideoUrl,
} from '../api/client';
import type { VideoMetadata, PlatformSpec, TTSPlatformConfig } from '../api/types';

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

  // Per-platform subtitle language override (empty string = use default from config)
  const [langOverrides, setLangOverrides] = useState<Record<string, string>>({});

  // TTS platform config (for auto-enabling when TTS audio exists)
  const [ttsPlatforms, setTtsPlatforms] = useState<Record<string, TTSPlatformConfig>>({});
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [volumeMix, setVolumeMix] = useState<Record<string, { original_volume: number; tts_volume: number }>>({});

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

  // Load TTS platform config
  const loadTtsData = useCallback(async () => {
    try {
      const platforms = await getTTSPlatforms();
      setTtsPlatforms(platforms);

      const initMix: Record<string, { original_volume: number; tts_volume: number }> = {};
      for (const [p, cfg] of Object.entries(platforms)) {
        initMix[p] = {
          original_volume: cfg.original_volume ?? 0.3,
          tts_volume: cfg.tts_volume ?? 1.0,
        };
      }
      setVolumeMix(initMix);
    } catch {
      // TTS not available
    }
  }, []);

  useEffect(() => {
    loadVideos();
    loadPlatforms();
    loadTtsData();
  }, [loadVideos, loadPlatforms, loadTtsData]);

  const selectedVideo = videos.find((v) => v.video_id === selectedVideoId);
  const activePlatforms = Object.entries(selectedPlatforms)
    .filter(([, v]) => v)
    .map(([k]) => k);

  const togglePlatform = (id: string) =>
    setSelectedPlatforms((prev) => ({ ...prev, [id]: !prev[id] }));

  const canProcess = selectedVideoId && activePlatforms.length > 0 && !isProcessing;

  // Get the effective subtitle language for a platform (override or default)
  const getEffectiveLang = (platform: string): string => {
    if (langOverrides[platform]) return langOverrides[platform];
    const spec = platformSpecs[platform];
    return spec?.subtitle_language || (platform === 'tiktok' || platform === 'facebook' ? 'vi' : 'en');
  };

  // Check if the effective subtitle language is available for this video
  const hasSubtitleForPlatform = (platform: string): boolean => {
    if (!selectedVideo) return false;
    const lang = getEffectiveLang(platform);
    return selectedVideo.srt_languages.includes(lang);
  };

  const setLangOverride = (platform: string, lang: string) => {
    setLangOverrides((prev) => {
      const next = { ...prev };
      if (lang === '') {
        delete next[platform]; // clear override, use default
      } else {
        next[platform] = lang;
      }
      return next;
    });
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

      // Build language overrides (only include platforms with non-default selections)
      const langOverridePayload: Record<string, string> = {};
      for (const p of activePlatforms) {
        if (langOverrides[p]) {
          langOverridePayload[p] = langOverrides[p];
        }
      }

      // Build TTS mix settings if TTS is enabled
      const ttsMixPayload: Record<string, { original_volume: number; tts_volume: number }> = {};
      if (ttsEnabled) {
        for (const p of activePlatforms) {
          if (volumeMix[p]) {
            ttsMixPayload[p] = volumeMix[p];
          }
        }
      }

      const { task_id } = await postProcess({
        video_id: selectedVideoId,
        platforms: activePlatforms,
        subtitle_style: styleOverride,
        subtitle_language_overrides: Object.keys(langOverridePayload).length > 0 ? langOverridePayload : undefined,
        enable_tts: ttsEnabled,
        tts_mix_settings: ttsEnabled ? ttsMixPayload : undefined,
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

  const updateVolumeMix = (platform: string, key: 'original_volume' | 'tts_volume', value: number) => {
    setVolumeMix((prev) => ({
      ...prev,
      [platform]: { ...(prev[platform] || { original_volume: 0.3, tts_volume: 1.0 }), [key]: value },
    }));
  };

  // Preview style (CSS approximation)
  const scaledFontSize = Math.max(12, fontSize * 0.65);
  const scaledOutline = Math.max(0.5, outlineWidth * 0.4);
  const previewStyle: React.CSSProperties = {
    fontFamily: fontName,
    fontSize: `${scaledFontSize}px`,
    fontWeight: boldEnabled ? 'bold' : 'normal',
    color: 'white',
    textShadow: shadowEnabled
      ? `0 0 ${scaledOutline}px black, 0 0 ${scaledOutline * 2}px black, 1px 1px 2px rgba(0,0,0,0.8)`
      : `0 0 ${scaledOutline}px black, 0 0 ${scaledOutline * 2}px black`,
    WebkitTextStroke: `${scaledOutline}px black`,
    lineHeight: '1.3',
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

            {/* Preview Frame — full thumbnail with subtitle overlay */}
            <div className="relative w-full min-h-[200px] rounded-lg overflow-hidden border border-outline-variant/10">
              {selectedVideo?.thumbnail ? (
                <img
                  src={selectedVideo.thumbnail}
                  alt="Preview"
                  className="w-full h-auto block"
                />
              ) : (
                <div className="w-full h-[200px] bg-gradient-to-b from-zinc-700 via-zinc-800 to-zinc-900 flex items-center justify-center">
                  <div className="flex flex-col items-center gap-2 opacity-40">
                    <span className="material-symbols-outlined text-white text-3xl">movie</span>
                    <span className="text-[10px] text-white/60">Select a video to preview</span>
                  </div>
                </div>
              )}
              {/* Bottom gradient for subtitle readability */}
              <div className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/70 to-transparent" />
              {/* Subtitle text */}
              <div
                className="absolute left-0 right-0 flex justify-center px-4 text-center"
                style={{ bottom: `${Math.max(8, verticalMargin * 0.5)}px` }}
              >
                <p style={previewStyle}>
                  Sample subtitle text preview
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
                      const effectiveLang = getEffectiveLang(id);
                      const hasSub = hasSubtitleForPlatform(id);
                      const availableLangs = selectedVideo?.srt_languages || [];

                      return (
                        <div
                          key={id}
                          className={`p-3 rounded-lg bg-surface-container-lowest border ${
                            selectedPlatforms[id] ? 'border-primary/30' : 'border-outline-variant/10'
                          } flex items-start gap-3 hover:border-primary/40 transition-colors`}
                        >
                          <input
                            checked={selectedPlatforms[id] || false}
                            onChange={() => togglePlatform(id)}
                            className="mt-1 rounded border-outline-variant bg-surface-container text-primary focus:ring-primary w-4 h-4 cursor-pointer"
                            type="checkbox"
                          />
                          <div className="flex-1">
                            <div className="flex justify-between items-center mb-1">
                              <span className="text-sm font-medium cursor-pointer" onClick={() => togglePlatform(id)}>{info.label}</span>
                              <span className="font-mono text-[9px] px-1.5 py-0.5 bg-zinc-800 text-zinc-400 rounded">
                                {info.constraint}
                              </span>
                            </div>
                            {/* Subtitle language selector */}
                            <div className="flex items-center gap-2 mt-1.5">
                              <span className="font-mono text-[9px] text-on-surface-variant uppercase">Subtitle:</span>
                              <select
                                value={langOverrides[id] || ''}
                                onChange={(e) => {
                                  e.stopPropagation();
                                  setLangOverride(id, e.target.value);
                                }}
                                onClick={(e) => e.stopPropagation()}
                                className="bg-surface-container-lowest border border-outline-variant/20 text-[11px] rounded px-1.5 py-0.5 focus:ring-1 focus:ring-primary text-on-surface"
                              >
                                <option value="">
                                  Default ({info.subLangLabel})
                                </option>
                                {availableLangs.map((lang) => (
                                  <option key={lang} value={lang}>
                                    {lang === 'en' ? 'English' : lang === 'vi' ? 'Vietnamese' : lang === 'zh' ? 'Chinese' : lang.toUpperCase()}
                                  </option>
                                ))}
                              </select>
                              <span className={`font-mono text-[9px] px-1.5 py-0.5 rounded uppercase ${
                                hasSub ? 'bg-primary/20 text-primary' : 'bg-amber-500/20 text-amber-400'
                              }`}>
                                {effectiveLang}
                              </span>
                            </div>
                            {!hasSub && selectedVideo && (
                              <p className="text-[10px] text-amber-400 flex items-center gap-1 mt-1">
                                <span className="material-symbols-outlined text-[12px]">warning</span>
                                {effectiveLang.toUpperCase()} SRT not available — will use fallback
                              </p>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* TTS Audio Mixing — toggle to include generated TTS in output */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="font-mono text-[10px] uppercase text-on-surface-variant">Mix TTS Audio</label>
                    <button
                      onClick={() => setTtsEnabled(!ttsEnabled)}
                      className={`w-10 h-5 rounded-full relative cursor-pointer transition-colors ${ttsEnabled ? 'bg-primary' : 'bg-surface-container-highest'}`}
                    >
                      <div className={`absolute top-0.5 w-4 h-4 bg-on-primary-fixed rounded-full transition-all ${ttsEnabled ? 'right-0.5' : 'left-0.5'}`} />
                    </button>
                  </div>

                  {ttsEnabled && (
                    <div className="bg-surface-container-lowest rounded-lg border border-outline-variant/10 p-4 space-y-3">
                      <p className="text-[10px] text-on-surface-variant">
                        Generate TTS audio on the <strong>Pipeline</strong> page first, then enable here to mix into output videos.
                      </p>

                      {/* Per-platform volume sliders */}
                      {activePlatforms.map((platform) => (
                        <div key={platform} className="space-y-1.5">
                          <span className="text-xs font-medium">
                            {PLATFORM_INFO[platform]?.label || platform}
                          </span>
                          <div className="grid grid-cols-2 gap-3">
                            <div className="space-y-0.5">
                              <div className="flex justify-between">
                                <span className="font-mono text-[8px] text-on-surface-variant">Original</span>
                                <span className="font-mono text-[8px] text-primary">
                                  {Math.round((volumeMix[platform]?.original_volume ?? 0.3) * 100)}%
                                </span>
                              </div>
                              <input
                                type="range" min={0} max={1} step={0.05}
                                value={volumeMix[platform]?.original_volume ?? 0.3}
                                onChange={(e) => updateVolumeMix(platform, 'original_volume', Number(e.target.value))}
                                className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                              />
                            </div>
                            <div className="space-y-0.5">
                              <div className="flex justify-between">
                                <span className="font-mono text-[8px] text-on-surface-variant">TTS Voice</span>
                                <span className="font-mono text-[8px] text-primary">
                                  {Math.round((volumeMix[platform]?.tts_volume ?? 1.0) * 100)}%
                                </span>
                              </div>
                              <input
                                type="range" min={0} max={1} step={0.05}
                                value={volumeMix[platform]?.tts_volume ?? 1.0}
                                onChange={(e) => updateVolumeMix(platform, 'tts_volume', Number(e.target.value))}
                                className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
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
                              {(langOverrides[platform] || platformSpecs[platform]?.subtitle_language || '').toUpperCase()}
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
