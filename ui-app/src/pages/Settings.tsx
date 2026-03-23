import { useState, useEffect } from 'react';
import { TopBar } from '../components/TopBar';
import {
  getCookieStatus,
  putCookie,
  testCookie,
  getConfig,
  putConfig,
} from '../api/client';
import type { CookieStatus, CookieTestResult } from '../api/client';
import { loadApiKeys, saveApiKey } from '../utils/storage';

function SettingsPage() {
  const [activeSection, setActiveSection] = useState('douyin');
  const [vadFilter, setVadFilter] = useState(true);

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
  const [whisperModelSize, setWhisperModelSize] = useState('large-v3');
  const [whisperDevice, setWhisperDevice] = useState('auto');
  const [whisperComputeType, setWhisperComputeType] = useState('float16');
  const [whisperLanguage, setWhisperLanguage] = useState('');
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

  useEffect(() => {
    getCookieStatus().then(setCookie).catch(() => {});
    // Load server config
    getConfig().then((cfg) => {
      const w = (cfg.whisper || {}) as Record<string, unknown>;
      const o = (cfg.ocr || {}) as Record<string, unknown>;
      const sr = (o.subtitle_region || {}) as Record<string, unknown>;
      const f = (cfg.ffmpeg || {}) as Record<string, unknown>;
      if (w.model_size) setWhisperModelSize(String(w.model_size));
      if (w.device) setWhisperDevice(String(w.device));
      if (w.compute_type) setWhisperComputeType(String(w.compute_type));
      if (w.default_language) setWhisperLanguage(String(w.default_language));
      if (w.vad_filter !== undefined) setVadFilter(Boolean(w.vad_filter));
      if (o.fps) setOcrFps(String(o.fps));
      if (o.crop_bottom_pct !== undefined) setOcrCropBottom(String(o.crop_bottom_pct));
      if (o.confidence_threshold) setOcrConfidence(String(o.confidence_threshold));
      if (o.similarity_threshold) setOcrSimilarity(String(o.similarity_threshold));
      if (sr.min_y) setOcrMinY(String(sr.min_y));
      if (sr.max_watermark_frequency) setOcrWatermarkFreq(String(sr.max_watermark_frequency));
      if (f.default_crf) setFfmpegCrf(Number(f.default_crf));
      if (f.preset) setFfmpegPreset(String(f.preset));
      if (f.audio_bitrate) setFfmpegAudioBitrate(String(f.audio_bitrate));
    }).catch(() => {});
    // Scroll to section if navigated with hash (e.g., /settings#apikeys)
    const hash = window.location.hash.replace('#', '');
    if (hash) {
      setTimeout(() => {
        setActiveSection(hash);
        document.getElementById(hash)?.scrollIntoView({ behavior: 'smooth' });
      }, 100);
    }
  }, []);

  const scrollToSection = (id: string) => {
    setActiveSection(id);
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
  };

  const sidebarItems = [
    { id: 'douyin', icon: 'api', label: 'Douyin API' },
    { id: 'apikeys', icon: 'key', label: 'API Keys' },
    { id: 'transcription', icon: 'description', label: 'Transcription' },
    { id: 'ocr', icon: 'document_scanner', label: 'OCR Subtitles' },
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

            {/* API Keys */}
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
                ] as const).map((provider) => (
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

            {/* Transcription */}
            <section className="space-y-6" id="transcription">
              <div className="border-b border-zinc-800/30 pb-4">
                <h2 className="text-xl font-semibold text-on-surface">Transcription</h2>
                <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">Whisper engine and VAD parameters.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Model Size</label>
                  <select className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm" value={whisperModelSize} onChange={(e) => setWhisperModelSize(e.target.value)}>
                    <option value="tiny">tiny</option>
                    <option value="base">base</option>
                    <option value="small">small</option>
                    <option value="medium">medium</option>
                    <option value="large-v3">large-v3</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Device</label>
                  <select className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" value={whisperDevice} onChange={(e) => setWhisperDevice(e.target.value)}>
                    <option value="auto">auto</option>
                    <option value="cpu">cpu</option>
                    <option value="cuda:0">cuda:0</option>
                    <option value="cuda:1">cuda:1</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Compute Type</label>
                  <select className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" value={whisperComputeType} onChange={(e) => setWhisperComputeType(e.target.value)}>
                    <option value="float16">float16</option>
                    <option value="int8_float16">int8_float16</option>
                    <option value="int8">int8</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Language</label>
                  <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm" placeholder="Auto (detect)" type="text" value={whisperLanguage} onChange={(e) => setWhisperLanguage(e.target.value)} />
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

            {/* OCR Subtitle Extraction */}
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
          <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-widest">
            {saveMsg || 'Changes saved to config.yaml on server'}
          </span>
        </div>
        <div className="flex gap-4">
          <button
            onClick={() => {
              getConfig().then((cfg) => {
                const w = (cfg.whisper || {}) as Record<string, unknown>;
                const o = (cfg.ocr || {}) as Record<string, unknown>;
                const sr = (o.subtitle_region || {}) as Record<string, unknown>;
                const f = (cfg.ffmpeg || {}) as Record<string, unknown>;
                setWhisperModelSize(String(w.model_size || 'large-v3'));
                setWhisperDevice(String(w.device || 'auto'));
                setWhisperComputeType(String(w.compute_type || 'float16'));
                setWhisperLanguage(String(w.default_language || ''));
                setVadFilter(w.vad_filter !== false);
                setOcrFps(String(o.fps || '2.0'));
                setOcrCropBottom(String(o.crop_bottom_pct || '0'));
                setOcrConfidence(String(o.confidence_threshold || '0.7'));
                setOcrSimilarity(String(o.similarity_threshold || '0.85'));
                setOcrMinY(String(sr.min_y || '0.65'));
                setOcrWatermarkFreq(String(sr.max_watermark_frequency || '0.80'));
                setFfmpegCrf(Number(f.default_crf) || 23);
                setFfmpegPreset(String(f.preset || 'medium'));
                setFfmpegAudioBitrate(String(f.audio_bitrate || '128k'));
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
                  whisper: {
                    model_size: whisperModelSize,
                    device: whisperDevice,
                    compute_type: whisperComputeType,
                    default_language: whisperLanguage || 'zh',
                    vad_filter: vadFilter,
                  },
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
