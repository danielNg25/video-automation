import { useEffect, useState } from 'react';
import { getConfig, putConfig } from '../../api/client';

// Find the closest matching option value for a numeric config value
function matchOption(val: unknown, options: string[]): string | null {
  if (val === undefined || val === null) return null;
  const num = Number(val);
  if (isNaN(num)) return String(val);
  // Find exact match first, then closest
  const exact = options.find((o) => Number(o) === num);
  return exact ?? String(val);
}

export function OcrSection() {
  const [ocrFps, setOcrFps] = useState('2.0');
  const [ocrConfidence, setOcrConfidence] = useState('0.7');
  const [ocrSimilarity, setOcrSimilarity] = useState('0.85');
  const [ocrMinY, setOcrMinY] = useState('0.65');
  const [ocrWatermarkFreq, setOcrWatermarkFreq] = useState('0.80');
  const [ocrCropBottom, setOcrCropBottom] = useState('0');
  const [saveMsg, setSaveMsg] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!saveMsg) return;
    const t = setTimeout(() => setSaveMsg(''), 2000);
    return () => clearTimeout(t);
  }, [saveMsg]);

  useEffect(() => {
    getConfig().then((cfg) => {
      const o = (cfg.ocr || {}) as Record<string, unknown>;
      const sr = (o.subtitle_region || {}) as Record<string, unknown>;
      const fpsMatch = matchOption(o.fps, ['1.0', '2.0', '3.0', '5.0']);
      if (fpsMatch) setOcrFps(fpsMatch);
      const cropMatch = matchOption(o.crop_bottom_pct, ['0', '0.20', '0.25', '0.30', '0.35', '0.40', '0.50']);
      if (cropMatch) setOcrCropBottom(cropMatch);
      const confMatch = matchOption(o.confidence_threshold, ['0.5', '0.6', '0.7', '0.8', '0.9']);
      if (confMatch) setOcrConfidence(confMatch);
      const simMatch = matchOption(o.similarity_threshold, ['0.7', '0.8', '0.85', '0.9', '0.95']);
      if (simMatch) setOcrSimilarity(simMatch);
      const minYMatch = matchOption(sr.min_y, ['0.00', '0.50', '0.55', '0.60', '0.65', '0.70', '0.75']);
      if (minYMatch) setOcrMinY(minYMatch);
      const wmMatch = matchOption(sr.max_watermark_frequency, ['0.70', '0.75', '0.80', '0.85', '0.90']);
      if (wmMatch) setOcrWatermarkFreq(wmMatch);
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
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
      });
      setSaveMsg('Saved.');
    } catch (e) {
      setSaveMsg(`Save failed: ${e instanceof Error ? e.message : 'unknown error'}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
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
            <option value="0.00">0% (full video — no position filter)</option>
            <option value="0.50">50% (wider — top-half subtitles)</option>
            <option value="0.55">55%</option>
            <option value="0.60">60%</option>
            <option value="0.65">65% (default)</option>
            <option value="0.70">70%</option>
            <option value="0.75">75% (bottom only)</option>
          </select>
          <p className="text-[10px] text-zinc-600">Only text below this % of frame height is considered a subtitle. Pick 0% to OCR the entire frame (combine with Pre-crop Bottom = 0% to keep top text)</p>
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
      <div className="flex items-center gap-3 pt-2">
        <button
          disabled={isSaving}
          onClick={handleSave}
          className="px-6 py-2.5 bg-primary text-on-primary-fixed text-xs font-bold uppercase tracking-widest rounded disabled:opacity-40 transition-all"
        >
          {isSaving ? 'Saving...' : 'Save OCR Settings'}
        </button>
        {saveMsg && (
          <span className={`text-xs font-mono ${saveMsg.toLowerCase().startsWith('save failed') || saveMsg.toLowerCase().includes('error') ? 'text-red-400' : 'text-emerald-400'}`}>
            {saveMsg}
          </span>
        )}
      </div>
    </section>
  );
}
