import { useState, useRef, useCallback } from 'react';
import { postTTSPreview } from '../api/client';

interface TTSPreviewProps {
  voice: string;
  provider?: string;
  speed?: string;
  pitch?: string;
  sampleText?: string;
}

export function TTSPreview({
  voice,
  provider = 'edge',
  speed = '+0%',
  pitch = '+0Hz',
  sampleText = 'Xin chào các bạn, hôm nay chúng ta sẽ nói về một chủ đề rất thú vị.',
}: TTSPreviewProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string>('');

  const handlePlay = useCallback(async () => {
    if (isPlaying && audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setIsPlaying(false);
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const blob = await postTTSPreview(sampleText, voice, provider, speed, pitch);
      // Clean up previous URL
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);

      const url = URL.createObjectURL(blob);
      urlRef.current = url;

      const audio = new Audio(url);
      audioRef.current = audio;

      audio.onended = () => setIsPlaying(false);
      audio.onerror = () => {
        setIsPlaying(false);
        setError('Playback failed');
      };

      await audio.play();
      setIsPlaying(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed');
    } finally {
      setIsLoading(false);
    }
  }, [voice, provider, speed, pitch, sampleText, isPlaying]);

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={handlePlay}
        disabled={isLoading}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
          isPlaying
            ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
            : 'bg-primary/10 text-primary hover:bg-primary/20'
        } ${isLoading ? 'opacity-50 cursor-wait' : ''}`}
      >
        <span className="material-symbols-outlined text-sm">
          {isLoading ? 'progress_activity' : isPlaying ? 'stop' : 'play_arrow'}
        </span>
        {isLoading ? 'Loading...' : isPlaying ? 'Stop' : 'Preview'}
      </button>
      {error && (
        <span className="text-[10px] text-red-400">{error}</span>
      )}
    </div>
  );
}
