import { useState, useRef, useCallback, useEffect } from 'react';
import type { SubtitleRegion } from '../../api/types';

interface RegionSelectorProps {
  frameUrl: string;
  region: SubtitleRegion | null;
  onRegionChange: (region: SubtitleRegion) => void;
  onAutoDetect?: () => void;
  loading?: boolean;
}

export function RegionSelector({ frameUrl, region, onRegionChange, onAutoDetect, loading }: RegionSelectorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [imgSize, setImgSize] = useState({ w: 0, h: 0, natW: 0, natH: 0 });

  const handleImgLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    setImgSize({
      w: img.clientWidth,
      h: img.clientHeight,
      natW: img.naturalWidth,
      natH: img.naturalHeight,
    });
  }, []);

  // Scale from video coords to display coords
  const scaleX = imgSize.natW > 0 ? imgSize.w / imgSize.natW : 1;
  const scaleY = imgSize.natH > 0 ? imgSize.h / imgSize.natH : 1;

  const handleMouseDown = useCallback((edge: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    setDragging(edge);
  }, []);

  useEffect(() => {
    if (!dragging || !region || !containerRef.current) return;

    const container = containerRef.current;
    const rect = container.getBoundingClientRect();

    const handleMouseMove = (e: MouseEvent) => {
      const mx = (e.clientX - rect.left) / scaleX;
      const my = (e.clientY - rect.top) / scaleY;

      const updated = { ...region };

      if (dragging === 'move') {
        updated.x = Math.max(0, Math.round(mx - region.width / 2));
        updated.y = Math.max(0, Math.round(my - region.height / 2));
      } else if (dragging === 'top') {
        const newY = Math.max(0, Math.round(my));
        updated.height = region.y + region.height - newY;
        updated.y = newY;
      } else if (dragging === 'bottom') {
        updated.height = Math.max(20, Math.round(my - region.y));
      } else if (dragging === 'left') {
        const newX = Math.max(0, Math.round(mx));
        updated.width = region.x + region.width - newX;
        updated.x = newX;
      } else if (dragging === 'right') {
        updated.width = Math.max(20, Math.round(mx - region.x));
      }

      onRegionChange({ ...updated, confidence: region.confidence, video_width: region.video_width, video_height: region.video_height });
    };

    const handleMouseUp = () => setDragging(null);

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [dragging, region, scaleX, scaleY, onRegionChange]);

  return (
    <div className="space-y-2">
      <div ref={containerRef} className="relative inline-block bg-black rounded-lg overflow-hidden select-none">
        <img
          src={frameUrl}
          alt="Video frame"
          className="block max-w-full max-h-[40vh]"
          onLoad={handleImgLoad}
          draggable={false}
        />

        {region && imgSize.w > 0 && (
          <div
            className="absolute border-2 border-dashed border-primary/80 bg-primary/10 cursor-move"
            style={{
              left: region.x * scaleX,
              top: region.y * scaleY,
              width: region.width * scaleX,
              height: region.height * scaleY,
            }}
            onMouseDown={handleMouseDown('move')}
          >
            {/* Edge handles */}
            <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-6 h-2 bg-primary rounded cursor-n-resize" onMouseDown={handleMouseDown('top')} />
            <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-6 h-2 bg-primary rounded cursor-s-resize" onMouseDown={handleMouseDown('bottom')} />
            <div className="absolute top-1/2 -left-1 -translate-y-1/2 w-2 h-6 bg-primary rounded cursor-w-resize" onMouseDown={handleMouseDown('left')} />
            <div className="absolute top-1/2 -right-1 -translate-y-1/2 w-2 h-6 bg-primary rounded cursor-e-resize" onMouseDown={handleMouseDown('right')} />
          </div>
        )}

        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/60">
            <span className="material-symbols-outlined text-primary animate-spin">progress_activity</span>
          </div>
        )}
      </div>

      {/* Coordinates display + auto-detect button */}
      <div className="flex items-center gap-3 text-[10px]">
        {region && (
          <span className="font-mono text-zinc-400">
            x:{region.x} y:{region.y} w:{region.width} h:{region.height}
          </span>
        )}
        {onAutoDetect && (
          <button
            onClick={onAutoDetect}
            className="px-2 py-1 rounded bg-surface-container-highest text-zinc-400 hover:text-on-surface text-[10px] font-bold uppercase"
          >
            Auto-detect
          </button>
        )}
      </div>
    </div>
  );
}
