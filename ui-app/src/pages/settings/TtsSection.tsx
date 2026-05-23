import { useState } from 'react';
import { storageGet, storageSet } from '../../utils/storage';

export function TtsSection() {
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

  return (
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
  );
}
