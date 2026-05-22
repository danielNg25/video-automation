import { useEffect, useState } from 'react';
import { getConfig, putConfig } from '../../api/client';

export function VideoExportSection() {
  const [ffmpegCrf, setFfmpegCrf] = useState(23);
  const [ffmpegPreset, setFfmpegPreset] = useState('medium');
  const [ffmpegAudioBitrate, setFfmpegAudioBitrate] = useState('128k');
  const [saveMsg, setSaveMsg] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!saveMsg) return;
    const t = setTimeout(() => setSaveMsg(''), 2000);
    return () => clearTimeout(t);
  }, [saveMsg]);

  useEffect(() => {
    getConfig().then((cfg) => {
      const f = (cfg.ffmpeg || {}) as Record<string, unknown>;
      if (f.default_crf) setFfmpegCrf(Number(f.default_crf));
      if (f.preset) setFfmpegPreset(String(f.preset));
      if (f.audio_bitrate) setFfmpegAudioBitrate(String(f.audio_bitrate));
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await putConfig({
        ffmpeg: {
          default_crf: ffmpegCrf,
          preset: ffmpegPreset,
          audio_bitrate: ffmpegAudioBitrate,
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
      <div className="flex items-center gap-3 pt-2">
        <button
          disabled={isSaving}
          onClick={handleSave}
          className="px-6 py-2.5 bg-primary text-on-primary-fixed text-xs font-bold uppercase tracking-widest rounded disabled:opacity-40 transition-all"
        >
          {isSaving ? 'Saving...' : 'Save Video Settings'}
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
