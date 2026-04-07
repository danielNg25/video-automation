import { useState, useCallback, useEffect } from 'react';
import { postPreviewBlur } from '../../api/client';
import type { SubtitleRegion, BlurSettings } from '../../api/types';

interface BlurPreviewProps {
  videoId: string;
  region: SubtitleRegion | null;
  blurSettings: BlurSettings;
  /** URL to the original (unblurred) frame */
  originalFrameUrl: string;
}

export function BlurPreview({ videoId, region, blurSettings, originalFrameUrl }: BlurPreviewProps) {
  const [blurredUrl, setBlurredUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showOriginal, setShowOriginal] = useState(false);

  const refreshPreview = useCallback(async () => {
    if (!region) return;
    setLoading(true);
    setError('');
    try {
      const blob = await postPreviewBlur(videoId, 5.0, blurSettings, region);
      const url = URL.createObjectURL(blob);
      setBlurredUrl(prev => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setLoading(false);
    }
  }, [videoId, region, blurSettings]);

  // Cleanup blob URL on unmount
  useEffect(() => {
    return () => {
      if (blurredUrl) URL.revokeObjectURL(blurredUrl);
    };
  }, [blurredUrl]);

  if (!region) {
    return (
      <div className="p-3 rounded-lg bg-surface-container text-zinc-500 text-xs text-center">
        No region selected — cannot generate blur preview
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <button
          onClick={refreshPreview}
          disabled={loading}
          className="px-3 py-1.5 rounded bg-surface-container-highest text-[10px] font-bold uppercase text-zinc-400 hover:text-on-surface disabled:opacity-50"
        >
          {loading ? (
            <span className="material-symbols-outlined text-xs animate-spin align-middle">progress_activity</span>
          ) : (
            'Refresh Preview'
          )}
        </button>

        {blurredUrl && (
          <label className="flex items-center gap-1.5 text-[10px] text-zinc-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showOriginal}
              onChange={e => setShowOriginal(e.target.checked)}
              className="accent-primary w-3 h-3"
            />
            Show original
          </label>
        )}
      </div>

      {error && (
        <div className="p-2 rounded bg-red-500/10 text-red-400 text-xs">{error}</div>
      )}

      {blurredUrl && (
        <div className="relative rounded-lg overflow-hidden bg-black inline-block">
          <img
            src={showOriginal ? originalFrameUrl : blurredUrl}
            alt={showOriginal ? 'Original frame' : 'Blurred frame'}
            className="block max-w-full max-h-[40vh]"
          />
          <div className="absolute top-2 left-2 px-2 py-0.5 rounded bg-black/70 text-[10px] font-bold uppercase text-zinc-300">
            {showOriginal ? 'Original' : 'Blurred'}
          </div>
        </div>
      )}
    </div>
  );
}
