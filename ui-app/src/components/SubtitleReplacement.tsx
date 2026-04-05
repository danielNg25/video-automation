import { useState, useEffect, useCallback } from 'react';
import { getSubtitleRegion, setSubtitleRegion, getSampleFrameUrl } from '../api/client';
import type { SubtitleRegion, BlurSettings } from '../api/types';
import { RegionSelector } from './editor/RegionSelector';
import { BlurPreview } from './editor/BlurPreview';

interface SubtitleReplacementProps {
  videoId: string;
  onBlurSettingsChange: (settings: BlurSettings | null, region: SubtitleRegion | null) => void;
}

const DEFAULT_BLUR: BlurSettings = {
  enabled: true,
  strength: 15,
  mode: 'blur',
  fill_color: '#000000',
};

export function SubtitleReplacement({ videoId, onBlurSettingsChange }: SubtitleReplacementProps) {
  const [expanded, setExpanded] = useState(false);
  const [region, setRegion] = useState<SubtitleRegion | null>(null);
  const [blurSettings, setBlurSettings] = useState<BlurSettings>(DEFAULT_BLUR);
  const [regionStatus, setRegionStatus] = useState<'loading' | 'detected' | 'none'>('loading');
  const [regionError, setRegionError] = useState('');
  const [frameLoading, setFrameLoading] = useState(false);

  const frameUrl = getSampleFrameUrl(videoId, 5.0);

  // Load auto-detected region
  useEffect(() => {
    setRegionStatus('loading');
    getSubtitleRegion(videoId)
      .then(r => {
        setRegion(r);
        setRegionStatus('detected');
      })
      .catch(() => {
        setRegionStatus('none');
      });
  }, [videoId]);

  // Propagate changes to parent
  useEffect(() => {
    if (blurSettings.enabled && region) {
      onBlurSettingsChange(blurSettings, region);
    } else {
      onBlurSettingsChange(null, null);
    }
  }, [blurSettings, region, onBlurSettingsChange]);

  const handleRegionChange = useCallback((updated: SubtitleRegion) => {
    setRegion(updated);
  }, []);

  const handleAutoDetect = useCallback(() => {
    setFrameLoading(true);
    getSubtitleRegion(videoId)
      .then(r => { setRegion(r); setRegionStatus('detected'); })
      .catch(() => setRegionError('Auto-detect failed'))
      .finally(() => setFrameLoading(false));
  }, [videoId]);

  const handleSaveRegion = useCallback(() => {
    if (!region) return;
    setSubtitleRegion(videoId, region).catch(() => {});
  }, [videoId, region]);

  const updateBlur = useCallback((patch: Partial<BlurSettings>) => {
    setBlurSettings(prev => ({ ...prev, ...patch }));
  }, []);

  return (
    <div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-4 flex justify-between items-center hover:bg-surface-container/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-primary text-lg">blur_on</span>
          <span className="text-xs font-bold uppercase tracking-widest">Original Subtitle Removal</span>
        </div>
        <div className="flex items-center gap-2">
          {regionStatus === 'detected' && (
            <span className="text-[10px] text-green-400 font-mono">Region detected</span>
          )}
          {regionStatus === 'none' && (
            <span className="text-[10px] text-zinc-500 font-mono">No OCR data</span>
          )}
          <span className={`material-symbols-outlined text-sm text-zinc-500 transition-transform ${expanded ? 'rotate-180' : ''}`}>
            expand_more
          </span>
        </div>
      </button>

      {expanded && (
        <div className="p-5 space-y-5 border-t border-outline-variant/10">
          {/* Enable toggle */}
          <div className="flex items-center gap-3">
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={blurSettings.enabled}
                onChange={e => updateBlur({ enabled: e.target.checked })}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-zinc-700 peer-checked:bg-primary rounded-full peer-focus:ring-2 peer-focus:ring-primary/30 transition-colors after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
            </label>
            <span className="text-xs text-on-surface">Blur original subtitles before burn-in</span>
          </div>

          {blurSettings.enabled && (
            <>
              {regionStatus === 'none' && (
                <div className="p-3 rounded-lg bg-zinc-800/50 border border-zinc-700/30 text-zinc-400 text-xs">
                  <span className="material-symbols-outlined text-sm align-middle mr-1">info</span>
                  No OCR metadata — this video was not transcribed via OCR. Blur is disabled.
                </div>
              )}

              {(regionStatus === 'detected' || region) && (
                <>
                  {/* Region Selector */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Subtitle Region</label>
                    <RegionSelector
                      frameUrl={frameUrl}
                      region={region}
                      onRegionChange={handleRegionChange}
                      onAutoDetect={handleAutoDetect}
                      loading={frameLoading}
                    />
                    {region && (
                      <button
                        onClick={handleSaveRegion}
                        className="px-2 py-1 rounded bg-surface-container-highest text-[10px] text-zinc-400 hover:text-on-surface font-bold uppercase"
                      >
                        Save Region
                      </button>
                    )}
                  </div>

                  {/* Blur Controls */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Blur Mode</label>
                      <select
                        value={blurSettings.mode}
                        onChange={e => updateBlur({ mode: e.target.value as BlurSettings['mode'] })}
                        className="w-full bg-surface-container border-none text-xs text-on-surface h-9 px-3 rounded-lg focus:ring-1 focus:ring-primary"
                      >
                        <option value="blur">Gaussian Blur</option>
                        <option value="pixelate">Pixelate</option>
                        <option value="fill">Solid Fill</option>
                      </select>
                    </div>

                    {blurSettings.mode !== 'fill' && (
                      <div className="space-y-1.5">
                        <div className="flex justify-between">
                          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Strength</label>
                          <span className="text-[10px] font-mono text-primary">{blurSettings.strength}</span>
                        </div>
                        <input
                          type="range" min={5} max={30} value={blurSettings.strength}
                          onChange={e => updateBlur({ strength: Number(e.target.value) })}
                          className="w-full accent-primary h-1 bg-surface-container-highest rounded-lg appearance-none cursor-pointer"
                        />
                      </div>
                    )}

                    {blurSettings.mode === 'fill' && (
                      <div className="space-y-1.5">
                        <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Fill Color</label>
                        <input
                          type="color"
                          value={blurSettings.fill_color}
                          onChange={e => updateBlur({ fill_color: e.target.value })}
                          className="w-full h-9 rounded-lg cursor-pointer bg-surface-container border-none"
                        />
                      </div>
                    )}
                  </div>

                  {/* Blur Preview */}
                  <div className="space-y-1.5">
                    <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold">Preview</label>
                    <BlurPreview
                      videoId={videoId}
                      region={region}
                      blurSettings={blurSettings}
                      originalFrameUrl={frameUrl}
                    />
                  </div>
                </>
              )}

              {regionError && (
                <div className="p-2 rounded bg-red-500/10 text-red-400 text-xs">{regionError}</div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
