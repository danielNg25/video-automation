import { forwardRef } from 'react';
import type { VideoPlayerState, VideoPlayerControls } from '../../hooks/useVideoPlayer';
import { formatDisplayTime } from '../../utils/srtTime';

interface VideoPlayerProps {
  src: string;
  state: VideoPlayerState;
  controls: VideoPlayerControls;
  children?: React.ReactNode;
  loading?: boolean;
  onLoadStart?: () => void;
  onCanPlay?: () => void;
}

const RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];

export const VideoPlayer = forwardRef<HTMLVideoElement, VideoPlayerProps>(
  ({ src, state, controls, children, loading, onLoadStart, onCanPlay }, ref) => {
    const { isPlaying, currentTime, duration, playbackRate, volume, isMuted } = state;

    return (
      <div className="relative bg-black rounded-lg overflow-hidden group">
        {/* Video element */}
        <div className="relative min-h-[200px]">
          <video
            ref={ref}
            src={src}
            className="w-full block"
            playsInline
            preload="auto"
            onClick={controls.togglePlay}
            onLoadStart={onLoadStart}
            onCanPlay={onCanPlay}
          />
          {/* Subtitle overlay (passed as children) */}
          {children}

          {/* Loading overlay */}
          {loading && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/80 gap-3">
              <span className="material-symbols-outlined text-primary text-3xl animate-spin">progress_activity</span>
              <span className="text-xs text-zinc-400 font-mono">Generating preview video...</span>
            </div>
          )}

          {/* Play/pause overlay icon */}
          {!isPlaying && !loading && (
            <div
              className="absolute inset-0 flex items-center justify-center cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={controls.togglePlay}
            >
              <div className="w-16 h-16 rounded-full bg-black/50 flex items-center justify-center backdrop-blur-sm">
                <span className="material-symbols-outlined text-white text-3xl ml-1">play_arrow</span>
              </div>
            </div>
          )}
        </div>

        {/* Controls bar */}
        <div className="bg-zinc-900/95 backdrop-blur-sm px-3 py-2 space-y-1.5">
          {/* Seek bar */}
          <input
            type="range"
            min={0}
            max={duration || 1}
            step={0.01}
            value={currentTime}
            onChange={(e) => controls.seek(Number(e.target.value))}
            className="w-full h-1 accent-primary cursor-pointer appearance-none bg-zinc-700 rounded-full [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary"
          />

          {/* Bottom row: play, time, speed, volume */}
          <div className="flex items-center gap-3 text-white">
            {/* Play/pause */}
            <button onClick={controls.togglePlay} className="hover:text-primary transition-colors">
              <span className="material-symbols-outlined text-xl">
                {isPlaying ? 'pause' : 'play_arrow'}
              </span>
            </button>

            {/* Frame step */}
            <button onClick={() => controls.stepFrame(-1)} className="hover:text-primary transition-colors" title="Previous frame">
              <span className="material-symbols-outlined text-lg">skip_previous</span>
            </button>
            <button onClick={() => controls.stepFrame(1)} className="hover:text-primary transition-colors" title="Next frame">
              <span className="material-symbols-outlined text-lg">skip_next</span>
            </button>

            {/* Time display */}
            <span className="font-mono text-[11px] text-zinc-300 select-none">
              {formatDisplayTime(currentTime)} / {formatDisplayTime(duration)}
            </span>

            <div className="flex-1" />

            {/* Playback speed */}
            <select
              value={playbackRate}
              onChange={(e) => controls.setPlaybackRate(Number(e.target.value))}
              className="bg-transparent text-[11px] text-zinc-300 border-none outline-none cursor-pointer font-mono"
            >
              {RATES.map((r) => (
                <option key={r} value={r} className="bg-zinc-900">
                  {r}x
                </option>
              ))}
            </select>

            {/* Volume */}
            <button onClick={controls.toggleMute} className="hover:text-primary transition-colors">
              <span className="material-symbols-outlined text-lg">
                {isMuted || volume === 0 ? 'volume_off' : volume < 0.5 ? 'volume_down' : 'volume_up'}
              </span>
            </button>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={isMuted ? 0 : volume}
              onChange={(e) => controls.setVolume(Number(e.target.value))}
              className="w-16 h-1 accent-primary cursor-pointer appearance-none bg-zinc-700 rounded-full [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-2.5 [&::-webkit-slider-thumb]:h-2.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary"
            />
          </div>
        </div>
      </div>
    );
  },
);

VideoPlayer.displayName = 'VideoPlayer';
