import { useState, useEffect, useCallback, useRef } from 'react';

export interface VideoPlayerState {
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  playbackRate: number;
  volume: number;
  isMuted: boolean;
}

export interface VideoPlayerControls {
  play: () => void;
  pause: () => void;
  togglePlay: () => void;
  seek: (time: number) => void;
  stepFrame: (direction: 1 | -1) => void;
  setPlaybackRate: (rate: number) => void;
  setVolume: (vol: number) => void;
  toggleMute: () => void;
}

export function useVideoPlayer(
  videoRef: React.RefObject<HTMLVideoElement | null>,
): [VideoPlayerState, VideoPlayerControls] {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackRate, setPlaybackRateState] = useState(1);
  const [volume, setVolumeState] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const rafRef = useRef<number>(0);

  // High-frequency time update via requestAnimationFrame
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const tick = () => {
      setCurrentTime(video.currentTime);
      rafRef.current = requestAnimationFrame(tick);
    };

    const onPlay = () => {
      setIsPlaying(true);
      rafRef.current = requestAnimationFrame(tick);
    };
    const onPause = () => {
      setIsPlaying(false);
      cancelAnimationFrame(rafRef.current);
      setCurrentTime(video.currentTime);
    };
    const onLoaded = () => {
      setDuration(video.duration);
      setCurrentTime(video.currentTime);
    };
    const onEnded = () => {
      setIsPlaying(false);
      cancelAnimationFrame(rafRef.current);
    };

    video.addEventListener('play', onPlay);
    video.addEventListener('pause', onPause);
    video.addEventListener('loadedmetadata', onLoaded);
    video.addEventListener('ended', onEnded);

    // If already loaded
    if (video.readyState >= 1) {
      setDuration(video.duration);
      setCurrentTime(video.currentTime);
    }

    return () => {
      cancelAnimationFrame(rafRef.current);
      video.removeEventListener('play', onPlay);
      video.removeEventListener('pause', onPause);
      video.removeEventListener('loadedmetadata', onLoaded);
      video.removeEventListener('ended', onEnded);
    };
  }, [videoRef]);

  const play = useCallback(() => videoRef.current?.play(), [videoRef]);
  const pause = useCallback(() => videoRef.current?.pause(), [videoRef]);
  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    v.paused ? v.play() : v.pause();
  }, [videoRef]);

  const seek = useCallback(
    (time: number) => {
      const v = videoRef.current;
      if (!v) return;
      v.currentTime = Math.max(0, Math.min(time, v.duration || Infinity));
      setCurrentTime(v.currentTime);
    },
    [videoRef],
  );

  const stepFrame = useCallback(
    (direction: 1 | -1) => {
      const v = videoRef.current;
      if (!v) return;
      v.currentTime = Math.max(0, v.currentTime + direction * (1 / 30));
      setCurrentTime(v.currentTime);
    },
    [videoRef],
  );

  const setPlaybackRate = useCallback(
    (rate: number) => {
      const v = videoRef.current;
      if (!v) return;
      v.playbackRate = rate;
      setPlaybackRateState(rate);
    },
    [videoRef],
  );

  const setVolume = useCallback(
    (vol: number) => {
      const v = videoRef.current;
      if (!v) return;
      v.volume = vol;
      setVolumeState(vol);
      if (vol > 0) setIsMuted(false);
    },
    [videoRef],
  );

  const toggleMute = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setIsMuted(v.muted);
  }, [videoRef]);

  const state: VideoPlayerState = { isPlaying, currentTime, duration, playbackRate, volume, isMuted };
  const controls: VideoPlayerControls = {
    play, pause, togglePlay, seek, stepFrame,
    setPlaybackRate, setVolume, toggleMute,
  };

  return [state, controls];
}
