import { useState, useEffect, useCallback } from 'react';

const BASE = '/api';

export interface PipelineRunChild {
  video_id: string;
  status: string;
  current_stage: string;
  progress: number;
  message: string;
  completed_stages: string[];
  error: string | null;
  title: string;
}

export interface PipelineRun {
  run_id: string;
  mode: 'single' | 'batch';
  urls: string[];
  platforms: string[];
  video_ids: string[];
  status: string;
  succeeded: number;
  failed: number;
  errors: { url: string; error: string }[];
  created_at: string;
  updated_at: string;
  children: PipelineRunChild[];
}

async function fetchRuns(): Promise<PipelineRun[]> {
  const res = await fetch(`${BASE}/pipeline/runs?limit=50`);
  if (!res.ok) return [];
  const data = await res.json();
  if (data.length > 0) return data as PipelineRun[];

  const hRes = await fetch(`${BASE}/pipeline/history?limit=50`);
  if (!hRes.ok) return [];
  const history = await hRes.json();
  return (history as Record<string, unknown>[]).map((h) => ({
    run_id: h.video_id as string,
    mode: 'single' as const,
    urls: [(h.url as string) || ''],
    platforms: (h.platforms as string[]) || [],
    video_ids: [h.video_id as string],
    status: h.status as string,
    succeeded: h.status === 'done' ? 1 : 0,
    failed: h.status === 'failed' ? 1 : 0,
    errors: h.error ? [{ url: (h.url as string) || '', error: h.error as string }] : [],
    created_at: (h.created_at as string) || '',
    updated_at: (h.updated_at as string) || '',
    children: [{
      video_id: h.video_id as string,
      status: h.status as string,
      current_stage: (h.current_stage as string) || '',
      progress: (h.progress as number) || 0,
      message: (h.message as string) || '',
      completed_stages: (h.completed_stages as string[]) || [],
      error: (h.error as string) || null,
      title: '',
    }],
  }));
}

export function usePipelineRuns(refreshIntervalMs = 30_000) {
  const [runs, setRuns] = useState<PipelineRun[]>([]);

  const refresh = useCallback(async () => {
    try {
      const next = await fetchRuns();
      if (next.length > 0) setRuns(next);
    } catch {
      // network/API not available — leave previous state
    }
  }, []);

  useEffect(() => {
    const load = async () => {
      try {
        const next = await fetchRuns();
        if (next.length > 0) setRuns(next);
      } catch {
        // ignore
      }
    };
    void load();
    const interval = setInterval(() => void load(), refreshIntervalMs);
    return () => clearInterval(interval);
  }, [refreshIntervalMs]);

  return { runs, refresh };
}

export function relativeTime(isoStr: string): string {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  } catch {
    return '';
  }
}

export function stageFromStatus(status: string): ('done' | 'active' | 'pending' | 'failed')[] {
  switch (status) {
    case 'done':
    case 'transcribed':
    case 'processed':
      return ['done', 'done', 'done', 'done'];
    case 'uploading':
      return ['done', 'done', 'done', 'active'];
    case 'processing':
      return ['done', 'done', 'active', 'pending'];
    case 'transcribing':
      return ['done', 'active', 'pending', 'pending'];
    case 'downloading':
      return ['active', 'pending', 'pending', 'pending'];
    case 'downloaded':
      return ['done', 'pending', 'pending', 'pending'];
    case 'failed':
      return ['failed', 'pending', 'pending', 'pending'];
    default:
      return ['pending', 'pending', 'pending', 'pending'];
  }
}
