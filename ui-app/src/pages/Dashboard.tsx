import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { getStats, getVideos } from '../api/client';
import type { DashboardStats, VideoMetadata } from '../api/types';

const BASE = '/api';

interface PipelineRun {
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
  children: {
    video_id: string;
    status: string;
    current_stage: string;
    progress: number;
    message: string;
    completed_stages: string[];
    error: string | null;
    title: string;
  }[];
}

const filterTabs = ['All', 'Running', 'Completed', 'Failed'] as const;

function stageFromStatus(status: string): ('done' | 'active' | 'pending' | 'failed')[] {
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

function relativeTime(isoStr: string): string {
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

export default function DashboardPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<string>('All');
  const [stats, setStats] = useState<DashboardStats>({
    totalVideos: 0,
    processedToday: 0,
    successRate: 100,
    activeTasks: 0,
  });
  const [videos, setVideos] = useState<VideoMetadata[]>([]);
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, v] = await Promise.all([getStats(), getVideos()]);
      setStats(s);
      setVideos(v.videos);
    } catch {
      // API not available
    }
    // Fetch pipeline runs, fall back to per-video history for legacy data
    try {
      const res = await fetch(`${BASE}/pipeline/runs?limit=50`);
      if (res.ok) {
        const data = await res.json();
        if (data.length > 0) {
          setRuns(data);
        } else {
          // No runs yet — synthesize from per-video history
          const hRes = await fetch(`${BASE}/pipeline/history?limit=50`);
          if (hRes.ok) {
            const history = await hRes.json();
            const legacyRuns: PipelineRun[] = history.map((h: Record<string, unknown>) => ({
              run_id: h.video_id as string,
              mode: 'single' as const,
              urls: [h.url as string || ''],
              platforms: (h.platforms as string[]) || [],
              video_ids: [h.video_id as string],
              status: h.status as string,
              succeeded: (h.status === 'done') ? 1 : 0,
              failed: (h.status === 'failed') ? 1 : 0,
              errors: h.error ? [{ url: (h.url as string) || '', error: h.error as string }] : [],
              created_at: h.created_at as string || '',
              updated_at: h.updated_at as string || '',
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
            setRuns(legacyRuns);
          }
        }
      }
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [refresh]);

  const filteredRuns = runs.filter((r) => {
    if (activeTab === 'All') return true;
    if (activeTab === 'Completed') return r.status === 'done' || r.status === 'skipped';
    if (activeTab === 'Failed') return r.status === 'failed';
    if (activeTab === 'Running') return r.status === 'running';
    return true;
  });

  void videos; // fetched for stats refresh

  const stageDotColor = (stage: string) => {
    switch (stage) {
      case 'done':
        return 'bg-emerald-500';
      case 'active':
        return 'bg-primary animate-pulse';
      case 'failed':
        return 'bg-error';
      default:
        return 'bg-surface-container-highest';
    }
  };

  const stageLabels = ['Download', 'Transcribe', 'Process', 'Upload'];

  return (
    <div className="flex flex-col h-full">
      <TopBar showSearch searchPlaceholder="Search tasks, videos or logs..." />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Stats Row */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-surface-container-low p-4 rounded-lg flex flex-col gap-1 group hover:bg-surface-container transition-colors">
            <span className="text-xs text-on-surface-variant font-medium uppercase tracking-wider">Total Videos</span>
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-mono font-semibold text-on-surface">{stats.totalVideos.toLocaleString()}</span>
              <span className="material-symbols-outlined text-on-surface-variant text-sm">video_library</span>
            </div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-lg flex flex-col gap-1 group hover:bg-surface-container transition-colors">
            <span className="text-xs text-on-surface-variant font-medium uppercase tracking-wider">Processed Today</span>
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-mono font-semibold text-on-surface">{stats.processedToday}</span>
              <span className="material-symbols-outlined text-on-surface-variant text-sm">today</span>
            </div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-lg flex flex-col gap-1 group hover:bg-surface-container transition-colors">
            <span className="text-xs text-on-surface-variant font-medium uppercase tracking-wider">Active Tasks</span>
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-mono font-semibold text-primary">
                {String(stats.activeTasks).padStart(2, '0')}
              </span>
              {stats.activeTasks > 0 && (
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Pipeline Status */}
        <div>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-title-sm font-semibold text-on-surface">Pipeline Status</h2>
              <div className="flex bg-surface-container-lowest p-1 rounded-md">
                {filterTabs.map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-3 py-1 text-[10px] uppercase font-bold tracking-tighter ${
                      activeTab === tab
                        ? 'bg-surface-container-high text-primary rounded-sm'
                        : 'text-on-surface-variant hover:text-on-surface'
                    }`}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            </div>
            <div className="bg-surface-container-low rounded-lg overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="text-[10px] uppercase tracking-widest text-on-surface-variant border-b border-outline-variant/10">
                    <th className="px-4 py-3 font-semibold">Run</th>
                    <th className="px-4 py-3 font-semibold text-center">Status</th>
                    <th className="px-4 py-3 font-semibold">Platforms</th>
                    <th className="px-4 py-3 font-semibold">Started</th>
                    <th className="px-4 py-3 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody className="text-xs">
                  {filteredRuns.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-zinc-500">
                        {runs.length === 0 ? 'No pipeline runs yet.' : 'No runs match this filter.'}
                      </td>
                    </tr>
                  ) : (
                    filteredRuns.slice(0, 20).map((run) => {
                      const isExpanded = expandedRow === run.run_id;
                      const isBatch = run.mode === 'batch';
                      const statusColor = run.status === 'done' ? 'text-emerald-400' : run.status === 'failed' ? 'text-error' : run.status === 'running' ? 'text-primary' : 'text-on-surface-variant';
                      const statusBg = run.status === 'done' ? 'bg-emerald-500/10' : run.status === 'failed' ? 'bg-error/10' : run.status === 'running' ? 'bg-primary/10' : 'bg-surface-container-highest';
                      return (
                        <React.Fragment key={run.run_id}>
                          <tr
                            onClick={() => setExpandedRow(isExpanded ? null : run.run_id)}
                            className="hover:bg-surface-container-high/50 transition-colors cursor-pointer group border-b border-outline-variant/5"
                          >
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-2">
                                <span className={`material-symbols-outlined text-sm ${isBatch ? 'text-primary' : 'text-on-surface-variant'}`}>
                                  {isBatch ? 'playlist_play' : 'play_arrow'}
                                </span>
                                <div className="flex flex-col">
                                  <span className="font-medium text-on-surface">
                                    {isBatch ? `Batch · ${run.urls.length} videos` : (run.children[0]?.title || run.urls[0]?.slice(0, 35) + '...')}
                                  </span>
                                  {isBatch && run.status === 'done' && (
                                    <span className="text-[9px] font-mono text-emerald-400">{run.succeeded} succeeded{run.failed > 0 ? `, ${run.failed} failed` : ''}</span>
                                  )}
                                  {!isBatch && (
                                    <span className="font-mono text-[9px] text-on-surface-variant">{run.video_ids[0] || ''}</span>
                                  )}
                                </div>
                              </div>
                            </td>
                            <td className="px-4 py-3 text-center">
                              <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded ${statusColor} ${statusBg}`}>
                                {run.status === 'running' && <span className="inline-block w-1.5 h-1.5 rounded-full bg-primary animate-pulse mr-1 align-middle" />}
                                {run.status}
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex gap-1">
                                {(run.platforms || []).map((p) => (
                                  <span key={p} className="text-[9px] font-mono bg-surface-container-highest px-1.5 py-0.5 rounded">{p}</span>
                                ))}
                              </div>
                            </td>
                            <td className="px-4 py-3 text-on-surface-variant font-mono text-[10px]">
                              {relativeTime(run.created_at)}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex gap-2">
                                {run.video_ids.length === 1 && (
                                  <button onClick={(e) => { e.stopPropagation(); navigate(`/videos/${run.video_ids[0]}`); }}
                                    className="text-[10px] text-primary hover:underline font-bold uppercase">View</button>
                                )}
                                {run.status === 'failed' && (
                                  <button onClick={async (e) => {
                                    e.stopPropagation();
                                    try {
                                      if (isBatch) {
                                        const failedUrls = run.errors.map(e => e.url);
                                        await fetch(`${BASE}/pipeline/batch`, {
                                          method: 'POST', headers: { 'Content-Type': 'application/json' },
                                          body: JSON.stringify({ urls: failedUrls, platforms: run.platforms, concurrency: 2, force: true }),
                                        });
                                      } else {
                                        await fetch(`${BASE}/pipeline/full`, {
                                          method: 'POST', headers: { 'Content-Type': 'application/json' },
                                          body: JSON.stringify({ url: run.urls[0], platforms: run.platforms, force: true }),
                                        });
                                      }
                                      refresh();
                                    } catch { /* ignore */ }
                                  }} className="text-[10px] text-error hover:underline font-bold uppercase">Retry</button>
                                )}
                              </div>
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr key={`${run.run_id}-detail`}>
                              <td colSpan={5} className="px-4 py-3 bg-surface-container-lowest">
                                {run.children.length > 0 ? (
                                  <div className="space-y-2">
                                    {run.children.map((child) => {
                                      const stages = stageFromStatus(child.status);
                                      return (
                                        <div key={child.video_id}
                                          className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-surface-container-low/50 cursor-pointer"
                                          onClick={(e) => { e.stopPropagation(); navigate(`/videos/${child.video_id}`); }}>
                                          <div className="flex gap-1" title={stageLabels.join(' → ')}>
                                            {stages.map((s, i) => (
                                              <div key={i} className={`w-1.5 h-1.5 rounded-full ${stageDotColor(s)}`} title={stageLabels[i]} />
                                            ))}
                                          </div>
                                          <span className="text-[11px] font-medium text-on-surface flex-1 truncate">
                                            {child.title || child.video_id}
                                          </span>
                                          <span className={`text-[9px] font-mono ${child.status === 'done' ? 'text-emerald-400' : child.status === 'failed' ? 'text-error' : 'text-on-surface-variant'}`}>
                                            {child.status === 'failed' ? child.error?.slice(0, 50) : (child.completed_stages || []).join(' → ') || child.status}
                                          </span>
                                          <span className="material-symbols-outlined text-xs text-zinc-600">arrow_forward</span>
                                        </div>
                                      );
                                    })}
                                  </div>
                                ) : (
                                  <div className="text-[11px] space-y-2">
                                    <div className="flex gap-6">
                                      <div>
                                        <span className="text-on-surface-variant font-mono uppercase text-[9px] block">URLs</span>
                                        {run.urls.map((u, i) => <p key={i} className="font-mono text-on-surface">{u}</p>)}
                                      </div>
                                    </div>
                                    {run.errors.length > 0 && (
                                      <div>
                                        <span className="text-on-surface-variant font-mono uppercase text-[9px] block">Errors</span>
                                        {run.errors.map((e, i) => <p key={i} className="text-error font-mono text-[10px]">{e.url}: {e.error}</p>)}
                                      </div>
                                    )}
                                  </div>
                                )}
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })
                  )}
                </tbody>
              </table>
              <div className="p-3 border-t border-outline-variant/10 flex justify-between items-center">
                <span className="text-[10px] font-mono text-on-surface-variant">
                  Showing {Math.min(filteredRuns.length, 20)} of {filteredRuns.length} runs
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Activity Feed — from pipeline runs */}
        <div className="space-y-4">
          <h2 className="text-title-sm font-semibold text-on-surface">Recent Activity</h2>
          <div className="bg-surface-container-low rounded-lg p-2 space-y-1">
            {runs.length === 0 ? (
              <div className="px-4 py-4 text-center text-zinc-500 text-xs">No activity yet</div>
            ) : (
              runs.slice(0, 20).map((run, i) => {
                const icon = run.status === 'done' ? 'check_circle' : run.status === 'failed' ? 'error' : run.status === 'running' ? 'sync' : 'pending';
                const color = run.status === 'done' ? 'text-emerald-500' : run.status === 'failed' ? 'text-error' : 'text-primary';
                const isBatch = run.mode === 'batch';
                const label = isBatch
                  ? `Batch (${run.urls.length} videos)`
                  : (run.children[0]?.title || run.video_ids[0]?.slice(0, 10) || run.urls[0]?.slice(0, 30));
                return (
                  <div key={`${run.run_id}-${i}`} className="flex items-center gap-4 px-4 py-2 hover:bg-surface-container-high/40 transition-colors">
                    <span className="font-mono text-[9px] text-zinc-600">{relativeTime(run.updated_at)}</span>
                    <span className={`material-symbols-outlined text-sm ${color}`}>{icon}</span>
                    <span className="text-[11px] text-on-surface">
                      <span className="font-mono font-bold">{label}</span>
                      {' — '}
                      {run.status === 'done'
                        ? `Completed${isBatch ? ` (${run.succeeded} ok${run.failed > 0 ? `, ${run.failed} failed` : ''})` : ` for ${run.platforms.join(', ')}`}`
                        : run.status === 'failed'
                          ? `Failed: ${run.errors[0]?.error?.slice(0, 60) || 'unknown'}`
                          : run.status}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
