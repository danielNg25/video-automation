import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import {
  getCookieStatus,
  putCookie,
  testCookie,
  getConfig,
  putConfig,
} from '../api/client';
import type { CookieStatus, CookieTestResult } from '../api/client';
import { loadApiKeys, saveApiKey, storageGet, storageSet } from '../utils/storage';

type CategoryId = 'douyin' | 'apikeys' | 'ocr' | 'translation' | 'tts' | 'video' | 'pipeline';

function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeCategory = (searchParams.get('category') as CategoryId) || 'douyin';
  const setActiveCategory = (id: CategoryId) =>
    setSearchParams(
      (p) => {
        p.set('category', id);
        return p;
      },
      { replace: true },
    );
  const [skipExisting, setSkipExisting] = useState(true);

  // Cookie management state
  const [cookie, setCookie] = useState<CookieStatus | null>(null);
  const [cookieInput, setCookieInput] = useState('');
  const [cookieSaving, setCookieSaving] = useState(false);
  const [cookieTesting, setCookieTesting] = useState(false);
  const [cookieTestResult, setCookieTestResult] = useState<CookieTestResult | null>(null);
  const [cookieSaveMsg, setCookieSaveMsg] = useState('');

  // API Keys state
  const [apiKeys, setApiKeys] = useState(loadApiKeys);
  const [apiKeySaveMsg, setApiKeySaveMsg] = useState('');

  // Server config state
  const [ocrFps, setOcrFps] = useState('2.0');
  const [ocrConfidence, setOcrConfidence] = useState('0.7');
  const [ocrSimilarity, setOcrSimilarity] = useState('0.85');
  const [ocrMinY, setOcrMinY] = useState('0.65');
  const [ocrWatermarkFreq, setOcrWatermarkFreq] = useState('0.80');
  const [ocrCropBottom, setOcrCropBottom] = useState('0');
  const [ffmpegCrf, setFfmpegCrf] = useState(23);
  const [ffmpegPreset, setFfmpegPreset] = useState('medium');
  const [ffmpegAudioBitrate, setFfmpegAudioBitrate] = useState('128k');
  const [saveMsg, setSaveMsg] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  // Pipeline section state
  const [pipelineDataDir, setPipelineDataDir] = useState('data');
  const [pipelineMaxConcurrent, setPipelineMaxConcurrent] = useState(3);
  const [pipelineRetryAttempts, setPipelineRetryAttempts] = useState(3);
  const [pipelineRetryDelay, setPipelineRetryDelay] = useState(10);

  // TTS Dubbing settings — shared with VideoDetail and DownloadTranscribe via
  // localStorage keys tts_playback_speed and tts_underlay_db.
  const [playbackSpeed, setPlaybackSpeed] = useState(() => {
    const v = parseFloat(storageGet('tts_playback_speed') || '');
    return Number.isFinite(v) && v >= 1.0 && v <= 2.0 ? v : 1.5;
  });
  const [underlayDb, setUnderlayDb] = useState(() => {
    const v = parseFloat(storageGet('tts_underlay_db') || '');
    return Number.isFinite(v) && v >= -24 && v <= 0 ? v : -18;
  });

  // Find the closest matching option value for a numeric config value
  const matchOption = (val: unknown, options: string[]): string | null => {
    if (val === undefined || val === null) return null;
    const num = Number(val);
    if (isNaN(num)) return String(val);
    // Find exact match first, then closest
    const exact = options.find((o) => Number(o) === num);
    return exact ?? String(val);
  };

  useEffect(() => {
    getCookieStatus().then(setCookie).catch(() => {});
    // Load server config
    getConfig().then((cfg) => {
      const o = (cfg.ocr || {}) as Record<string, unknown>;
      const sr = (o.subtitle_region || {}) as Record<string, unknown>;
      const f = (cfg.ffmpeg || {}) as Record<string, unknown>;
      const fpsMatch = matchOption(o.fps, ['1.0', '2.0', '3.0', '5.0']);
      if (fpsMatch) setOcrFps(fpsMatch);
      const cropMatch = matchOption(o.crop_bottom_pct, ['0', '0.20', '0.25', '0.30', '0.35', '0.40', '0.50']);
      if (cropMatch) setOcrCropBottom(cropMatch);
      const confMatch = matchOption(o.confidence_threshold, ['0.5', '0.6', '0.7', '0.8', '0.9']);
      if (confMatch) setOcrConfidence(confMatch);
      const simMatch = matchOption(o.similarity_threshold, ['0.7', '0.8', '0.85', '0.9', '0.95']);
      if (simMatch) setOcrSimilarity(simMatch);
      const minYMatch = matchOption(sr.min_y, ['0.50', '0.55', '0.60', '0.65', '0.70', '0.75']);
      if (minYMatch) setOcrMinY(minYMatch);
      const wmMatch = matchOption(sr.max_watermark_frequency, ['0.70', '0.75', '0.80', '0.85', '0.90']);
      if (wmMatch) setOcrWatermarkFreq(wmMatch);
      if (f.default_crf) setFfmpegCrf(Number(f.default_crf));
      if (f.preset) setFfmpegPreset(String(f.preset));
      if (f.audio_bitrate) setFfmpegAudioBitrate(String(f.audio_bitrate));
      // Pipeline settings
      const p = (cfg.pipeline || {}) as Record<string, unknown>;
      if (p.data_dir) setPipelineDataDir(String(p.data_dir));
      if (p.max_concurrent) setPipelineMaxConcurrent(Number(p.max_concurrent));
      if (p.retry_attempts) setPipelineRetryAttempts(Number(p.retry_attempts));
      if (p.retry_delay) setPipelineRetryDelay(Number(p.retry_delay));
      if (p.skip_existing !== undefined) setSkipExisting(Boolean(p.skip_existing));
    }).catch(() => {});
  }, []);

  const categoryGroups: { group: string; items: { id: CategoryId; icon: string; label: string }[] }[] = [
    {
      group: 'SOURCES',
      items: [
        { id: 'douyin', icon: 'api', label: 'Douyin API' },
        { id: 'apikeys', icon: 'key', label: 'API Keys' },
      ],
    },
    {
      group: 'PROCESSING',
      items: [
        { id: 'ocr', icon: 'document_scanner', label: 'Subtitles (OCR)' },
        { id: 'translation', icon: 'translate', label: 'Translation' },
        { id: 'tts', icon: 'record_voice_over', label: 'Dubbing (TTS)' },
        { id: 'video', icon: 'movie_filter', label: 'Export & Video' },
      ],
    },
    {
      group: 'SYSTEM',
      items: [
        { id: 'pipeline', icon: 'account_tree', label: 'Pipeline' },
      ],
    },
  ];

  return (
    <div className="flex flex-col h-full bg-surface">
      <TopBar breadcrumb="Settings" />

      {/* Settings Workspace */}
      <div className="flex flex-1 overflow-hidden">
        {/* Settings Sidebar (Sub-nav) */}
        <nav className="w-56 bg-surface-container-lowest flex flex-col p-2 gap-2 border-r border-zinc-800/10 overflow-y-auto">
          {categoryGroups.map((g) => (
            <div key={g.group} className="space-y-0.5">
              <div className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 px-3 pt-2 pb-1">{g.group}</div>
              {g.items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setActiveCategory(item.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded text-sm font-medium transition-colors text-left ${
                    activeCategory === item.id
                      ? 'bg-surface-container-high text-primary'
                      : 'text-zinc-400 hover:bg-surface-container-low'
                  }`}
                >
                  <span className="material-symbols-outlined text-[18px]">{item.icon}</span>
                  {item.label}
                </button>
              ))}
            </div>
          ))}
        </nav>

        {/* Settings Content */}
        <div className="flex-1 overflow-y-auto p-8">
          <div className="max-w-3xl mx-auto pb-12">
            {activeCategory === 'douyin' && (
            <section className="space-y-6" id="douyin">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">Douyin API</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">Cookie and service configuration.</p>
              </div>

              {/* Service URL */}
              <div className="space-y-2">
                <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Service URL</label>
                <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono text-primary" type="text" defaultValue="http://localhost:8080" />
              </div>

              {/* Cookie Management */}
              <div className="bg-surface-container-low p-5 rounded-lg space-y-4">
                {/* Status header */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-bold uppercase tracking-widest text-zinc-500">Cookie</span>
                    {cookie?.exists ? (
                      <span className="text-[10px] font-mono bg-emerald-900/30 text-emerald-400 px-2 py-0.5 rounded">
                        ACTIVE ({cookie.length} chars)
                      </span>
                    ) : (
                      <span className="text-[10px] font-mono bg-red-900/30 text-red-400 px-2 py-0.5 rounded">
                        {cookie === null ? 'LOADING...' : 'MISSING'}
                      </span>
                    )}
                  </div>
                  {cookie?.preview && (
                    <span className="text-xs font-mono text-zinc-500">{cookie.preview}</span>
                  )}
                </div>

                {/* File path */}
                {cookie?.file_path && (
                  <p className="text-[10px] font-mono text-zinc-600">{cookie.file_path}</p>
                )}

                {/* Paste new cookie */}
                <textarea
                  className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono resize-none text-on-surface"
                  rows={3}
                  placeholder="Paste new cookie string here..."
                  value={cookieInput}
                  onChange={(e) => setCookieInput(e.target.value)}
                />

                {/* Action buttons */}
                <div className="flex items-center gap-3">
                  <button
                    disabled={!cookieInput.trim() || cookieSaving}
                    onClick={async () => {
                      setCookieSaving(true);
                      setCookieSaveMsg('');
                      try {
                        const updated = await putCookie(cookieInput);
                        setCookie(updated);
                        setCookieInput('');
                        setCookieSaveMsg('Saved');
                        setCookieTestResult(null);
                        setTimeout(() => setCookieSaveMsg(''), 3000);
                      } catch (e: unknown) {
                        setCookieSaveMsg(e instanceof Error ? e.message : 'Save failed');
                      } finally {
                        setCookieSaving(false);
                      }
                    }}
                    className="px-5 py-2.5 bg-primary text-on-primary-fixed text-xs font-bold uppercase tracking-widest rounded disabled:opacity-40 transition-all"
                  >
                    {cookieSaving ? 'Saving...' : 'Save Cookie'}
                  </button>
                  <button
                    disabled={!cookie?.exists || cookieTesting}
                    onClick={async () => {
                      setCookieTesting(true);
                      setCookieTestResult(null);
                      try {
                        const result = await testCookie();
                        setCookieTestResult(result);
                      } catch (e: unknown) {
                        setCookieTestResult({ success: false, message: e instanceof Error ? e.message : 'Test failed' });
                      } finally {
                        setCookieTesting(false);
                      }
                    }}
                    className="px-5 py-2.5 bg-surface-container-high hover:bg-surface-variant text-xs font-bold uppercase tracking-widest rounded disabled:opacity-40 transition-colors"
                  >
                    {cookieTesting ? 'Testing...' : 'Test Cookie'}
                  </button>
                  {cookieSaveMsg && (
                    <span className="text-xs font-mono text-emerald-400">{cookieSaveMsg}</span>
                  )}
                </div>

                {/* Test result */}
                {cookieTestResult && (
                  <div className={`flex items-center gap-2 text-xs font-mono ${cookieTestResult.success ? 'text-emerald-400' : 'text-red-400'}`}>
                    <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>
                      {cookieTestResult.success ? 'check_circle' : 'error'}
                    </span>
                    {cookieTestResult.message}
                  </div>
                )}
              </div>
            </section>
            )}

            {activeCategory === 'apikeys' && (
            <section className="space-y-6" id="apikeys">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">API Keys</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">LLM provider keys for subtitle translation. Stored in browser only.</p>
              </div>
              <div className="bg-surface-container-low p-5 rounded-lg space-y-5">
                <div className="flex items-center gap-2 text-[10px] font-mono text-zinc-500">
                  <span className="material-symbols-outlined text-sm">lock</span>
                  Keys are saved in your browser&apos;s localStorage — never sent to our server, only to the provider&apos;s API directly.
                </div>

                {([
                  { key: 'anthropic', label: 'Anthropic', placeholder: 'sk-ant-...', icon: 'neurology' },
                  { key: 'openai', label: 'OpenAI', placeholder: 'sk-...', icon: 'psychology' },
                  { key: 'deepseek', label: 'DeepSeek', placeholder: 'sk-...', icon: 'model_training' },
                  { key: 'elevenlabs', label: 'ElevenLabs', placeholder: 'xi-...', icon: 'record_voice_over' },
                  { key: 'google', label: 'Google Cloud', placeholder: 'AIza...', icon: 'cloud' },
                ] as { key: string; label: string; placeholder: string; icon: string }[]).map((provider) => (
                  <div key={provider.key} className="space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-sm text-zinc-400">{provider.icon}</span>
                      <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">{provider.label}</label>
                      {apiKeys[provider.key] && (
                        <span className="text-[10px] font-mono bg-emerald-900/30 text-emerald-400 px-2 py-0.5 rounded">SAVED</span>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <input
                        type="password"
                        className="flex-1 bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono text-on-surface"
                        placeholder={provider.placeholder}
                        value={apiKeys[provider.key]}
                        onChange={(e) => setApiKeys({ ...apiKeys, [provider.key]: e.target.value })}
                      />
                      <button
                        onClick={() => {
                          saveApiKey(provider.key, apiKeys[provider.key]);
                          setApiKeySaveMsg(`${provider.label} key saved`);
                          setTimeout(() => setApiKeySaveMsg(''), 3000);
                        }}
                        className="px-4 py-2 bg-primary text-on-primary-fixed text-xs font-bold uppercase tracking-widest rounded"
                      >
                        Save
                      </button>
                      {apiKeys[provider.key] && (
                        <button
                          onClick={() => {
                            saveApiKey(provider.key, '');
                            setApiKeys({ ...apiKeys, [provider.key]: '' });
                            setApiKeySaveMsg(`${provider.label} key removed`);
                            setTimeout(() => setApiKeySaveMsg(''), 3000);
                          }}
                          className="px-3 py-2 bg-surface-container-high hover:bg-error/10 hover:text-error text-xs font-bold uppercase tracking-widest rounded transition-colors"
                        >
                          Clear
                        </button>
                      )}
                    </div>
                  </div>
                ))}

                {apiKeySaveMsg && (
                  <div className="flex items-center gap-2 text-xs font-mono text-emerald-400">
                    <span className="material-symbols-outlined text-sm">check_circle</span>
                    {apiKeySaveMsg}
                  </div>
                )}
              </div>
            </section>
            )}

            {activeCategory === 'ocr' && (
            <section className="space-y-6" id="ocr">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">OCR Subtitle Extraction</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">PaddleOCR settings for extracting burned-in subtitles from video frames.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Frames Per Second</label>
                  <select
                    className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono"
                    value={ocrFps}
                    onChange={(e) => setOcrFps(e.target.value)}
                  >
                    <option value="1.0">1.0 (faster)</option>
                    <option value="2.0">2.0 (default)</option>
                    <option value="3.0">3.0 (more accurate)</option>
                    <option value="5.0">5.0 (high detail)</option>
                  </select>
                  <p className="text-[10px] text-zinc-600">Higher FPS = more frames to OCR = slower but catches fast subtitles</p>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Pre-crop Bottom %</label>
                  <select
                    className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono"
                    value={ocrCropBottom}
                    onChange={(e) => setOcrCropBottom(e.target.value)}
                  >
                    <option value="0">Off (full frame)</option>
                    <option value="0.20">20% (bottom fifth)</option>
                    <option value="0.25">25% (recommended)</option>
                    <option value="0.30">30%</option>
                    <option value="0.35">35%</option>
                    <option value="0.40">40%</option>
                    <option value="0.50">50% (bottom half)</option>
                  </select>
                  <p className="text-[10px] text-zinc-600">Crop frame to bottom N% before OCR. Speeds up 3-5x by reducing scan area</p>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Confidence Threshold</label>
                  <select
                    className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono"
                    value={ocrConfidence}
                    onChange={(e) => setOcrConfidence(e.target.value)}
                  >
                    <option value="0.5">0.5 (loose)</option>
                    <option value="0.6">0.6</option>
                    <option value="0.7">0.7 (default)</option>
                    <option value="0.8">0.8</option>
                    <option value="0.9">0.9 (strict)</option>
                  </select>
                  <p className="text-[10px] text-zinc-600">Min OCR confidence to accept a detection. Lower = more text but more noise</p>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Similarity Threshold</label>
                  <select
                    className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono"
                    value={ocrSimilarity}
                    onChange={(e) => setOcrSimilarity(e.target.value)}
                  >
                    <option value="0.7">0.7 (loose merge)</option>
                    <option value="0.8">0.8</option>
                    <option value="0.85">0.85 (default)</option>
                    <option value="0.9">0.9</option>
                    <option value="0.95">0.95 (strict)</option>
                  </select>
                  <p className="text-[10px] text-zinc-600">How similar consecutive frames must be to merge into one subtitle segment</p>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Subtitle Region (min Y%)</label>
                  <select
                    className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono"
                    value={ocrMinY}
                    onChange={(e) => setOcrMinY(e.target.value)}
                  >
                    <option value="0.50">50% (wider — top-half subtitles)</option>
                    <option value="0.55">55%</option>
                    <option value="0.60">60%</option>
                    <option value="0.65">65% (default)</option>
                    <option value="0.70">70%</option>
                    <option value="0.75">75% (bottom only)</option>
                  </select>
                  <p className="text-[10px] text-zinc-600">Only text below this % of frame height is considered a subtitle</p>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Watermark Frequency</label>
                  <select
                    className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono"
                    value={ocrWatermarkFreq}
                    onChange={(e) => setOcrWatermarkFreq(e.target.value)}
                  >
                    <option value="0.70">70%</option>
                    <option value="0.75">75%</option>
                    <option value="0.80">80% (default)</option>
                    <option value="0.85">85%</option>
                    <option value="0.90">90% (less filtering)</option>
                  </select>
                  <p className="text-[10px] text-zinc-600">Text at same position in more than this % of frames is classified as watermark</p>
                </div>
              </div>
            </section>
            )}

            {activeCategory === 'translation' && (
              <div className="bg-surface-container-low rounded-xl p-6 text-center text-on-surface-variant">
                <p className="text-sm">Translation defaults — coming in Task 11.</p>
                <p className="text-xs mt-2">Manage translation style profiles on the <a href="/profiles" className="text-primary underline">Translation Profiles</a> page.</p>
              </div>
            )}

            {activeCategory === 'video' && (
            <section className="space-y-6" id="video">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">Video Processing</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">FFmpeg encoding and rendering defaults.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8 bg-surface-container-low/50 p-6 rounded-lg">
                <div className="space-y-4">
                  <div className="flex justify-between items-center">
                    <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">CRF (Quality)</label>
                    <span className="text-xs font-mono text-primary">{ffmpegCrf}</span>
                  </div>
                  <input
                    className="w-full h-1.5 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                    max={51}
                    min={0}
                    type="range"
                    value={ffmpegCrf}
                    onChange={(e) => setFfmpegCrf(Number(e.target.value))}
                  />
                  <div className="flex justify-between text-[10px] font-mono text-zinc-600">
                    <span>LOSSLESS (0)</span>
                    <span>LOW QUAL (51)</span>
                  </div>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Preset</label>
                  <select className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" value={ffmpegPreset} onChange={(e) => setFfmpegPreset(e.target.value)}>
                    <option value="ultrafast">ultrafast</option>
                    <option value="superfast">superfast</option>
                    <option value="veryfast">veryfast</option>
                    <option value="faster">faster</option>
                    <option value="medium">medium</option>
                    <option value="slow">slow</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Audio Bitrate</label>
                  <div className="flex items-center">
                    <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded-l p-3 text-sm font-mono" type="text" value={ffmpegAudioBitrate} onChange={(e) => setFfmpegAudioBitrate(e.target.value)} />
                    <span className="bg-surface-container-highest px-4 py-3 border-y border-r border-outline-variant/20 text-xs font-mono text-zinc-500 rounded-r">kbps</span>
                  </div>
                </div>
              </div>
            </section>
            )}

            {activeCategory === 'tts' && (
            <section className="space-y-6" id="tts">
              <div className="border-b border-zinc-800/30 pb-4">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary">record_voice_over</span>
                  <h2 className="text-xl font-semibold text-on-surface">TTS Dubbing</h2>
                </div>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">Playback speed and underlay defaults shared across all pipeline flows.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-on-surface mb-2">
                    Dub playback speed
                  </label>
                  <input
                    type="number" min={1.0} max={2.0} step={0.1}
                    value={playbackSpeed}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      if (Number.isFinite(v) && v >= 1.0 && v <= 2.0) {
                        setPlaybackSpeed(v);
                        storageSet('tts_playback_speed', String(v));
                      }
                    }}
                    className="w-full px-3 py-2 rounded border border-outline-variant/30 bg-surface-container-low text-sm"
                  />
                  <p className="text-xs text-on-surface-variant mt-1">
                    Every dubbed sentence plays at this speed (uniform pacing).
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-on-surface mb-2">
                    Original-language underlay
                  </label>
                  <select
                    value={String(underlayDb)}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      setUnderlayDb(v);
                      storageSet('tts_underlay_db', String(v));
                    }}
                    className="w-full px-3 py-2 rounded border border-outline-variant/30 bg-surface-container-low text-sm"
                  >
                    <option value="0">Off</option>
                    <option value="-24">-24 dB (subliminal)</option>
                    <option value="-18">-18 dB (quiet)</option>
                    <option value="-12">-12 dB (audible)</option>
                    <option value="-6">-6 dB (strong)</option>
                  </select>
                  <p className="text-xs text-on-surface-variant mt-1">
                    The source Chinese voice sits under the dub at this level.
                  </p>
                </div>
              </div>
            </section>
            )}

            {activeCategory === 'pipeline' && (
            <section className="space-y-6" id="pipeline">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">Pipeline</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">Batch processing and concurrency management.</p>
              </div>
              <div className="space-y-6">
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Data Directory</label>
                  <div className="flex gap-2">
                    <input className="flex-1 bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="text" value={pipelineDataDir} onChange={(e) => setPipelineDataDir(e.target.value)} />
                    <button className="px-4 py-2 bg-surface-container-high hover:bg-surface-variant transition-colors rounded">
                      <span className="material-symbols-outlined text-zinc-400">folder_open</span>
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Max Concurrent</label>
                    <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="number" min={1} max={10} value={pipelineMaxConcurrent} onChange={(e) => setPipelineMaxConcurrent(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Retry Attempts</label>
                    <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="number" min={1} max={5} value={pipelineRetryAttempts} onChange={(e) => setPipelineRetryAttempts(Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Retry Delay (s)</label>
                    <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="number" min={1} max={120} value={pipelineRetryDelay} onChange={(e) => setPipelineRetryDelay(Number(e.target.value))} />
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
            )}
          </div>
        </div>
      </div>

      {/* Sticky Footer */}
      <div className="absolute bottom-0 left-0 right-0 bg-surface/80 backdrop-blur-md border-t border-zinc-800/30 px-8 py-4 flex justify-between items-center z-50">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-emerald-500 text-sm">cloud_done</span>
          <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-widest">
            {saveMsg || 'Changes saved to config.yaml on server'}
          </span>
        </div>
        <div className="flex gap-4">
          <button
            onClick={() => {
              getConfig().then((cfg) => {
                const o = (cfg.ocr || {}) as Record<string, unknown>;
                const sr = (o.subtitle_region || {}) as Record<string, unknown>;
                const f = (cfg.ffmpeg || {}) as Record<string, unknown>;
                setOcrFps(String(o.fps || '2.0'));
                setOcrCropBottom(String(o.crop_bottom_pct || '0'));
                setOcrConfidence(String(o.confidence_threshold || '0.7'));
                setOcrSimilarity(String(o.similarity_threshold || '0.85'));
                setOcrMinY(String(sr.min_y || '0.65'));
                setOcrWatermarkFreq(String(sr.max_watermark_frequency || '0.80'));
                setFfmpegCrf(Number(f.default_crf) || 23);
                setFfmpegPreset(String(f.preset || 'medium'));
                setFfmpegAudioBitrate(String(f.audio_bitrate || '128k'));
                const p = (cfg.pipeline || {}) as Record<string, unknown>;
                setPipelineDataDir(String(p.data_dir || 'data'));
                setPipelineMaxConcurrent(Number(p.max_concurrent) || 3);
                setPipelineRetryAttempts(Number(p.retry_attempts) || 3);
                setPipelineRetryDelay(Number(p.retry_delay) || 10);
                setSkipExisting(p.skip_existing !== false);
                setSaveMsg('Reset to server defaults');
                setTimeout(() => setSaveMsg(''), 3000);
              });
            }}
            className="px-6 py-2 rounded text-xs font-bold uppercase tracking-widest text-zinc-400 hover:text-on-surface transition-colors"
          >
            Discard
          </button>
          <button
            disabled={isSaving}
            onClick={async () => {
              setIsSaving(true);
              try {
                await putConfig({
                  ocr: {
                    fps: Number(ocrFps),
                    crop_bottom_pct: Number(ocrCropBottom),
                    confidence_threshold: Number(ocrConfidence),
                    similarity_threshold: Number(ocrSimilarity),
                    subtitle_region: {
                      min_y: Number(ocrMinY),
                      max_watermark_frequency: Number(ocrWatermarkFreq),
                    },
                  },
                  ffmpeg: {
                    default_crf: ffmpegCrf,
                    preset: ffmpegPreset,
                    audio_bitrate: ffmpegAudioBitrate,
                  },
                  pipeline: {
                    data_dir: pipelineDataDir,
                    max_concurrent: pipelineMaxConcurrent,
                    retry_attempts: pipelineRetryAttempts,
                    retry_delay: pipelineRetryDelay,
                    skip_existing: skipExisting,
                  },
                });
                setSaveMsg('Settings saved to config.yaml');
                setTimeout(() => setSaveMsg(''), 3000);
              } catch (e) {
                setSaveMsg(`Save failed: ${e instanceof Error ? e.message : 'unknown error'}`);
              } finally {
                setIsSaving(false);
              }
            }}
            className="px-8 py-2.5 bg-gradient-to-br from-primary to-primary-container text-on-primary-fixed font-bold text-xs uppercase tracking-widest rounded shadow-lg shadow-primary/20 active:scale-95 transition-all disabled:opacity-50"
          >
            {isSaving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default SettingsPage;
