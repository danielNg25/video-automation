import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '../components/TopBar';
import { getStats, getVideos, postDownload, subscribeSSE } from '../api/client';
import type { DashboardStats, VideoMetadata } from '../api/types';
import type { PipelineHistoryEntry } from '../api/types';

const BASE = '/api';

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
  const [history, setHistory] = useState<PipelineHistoryEntry[]>([]);
  const [quickUrl, setQuickUrl] = useState('');
  const [quickDownloading, setQuickDownloading] = useState(false);
  const [batchUrls, setBatchUrls] = useState('');
  const [batchConcurrency, setBatchConcurrency] = useState(3);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchProgress, setBatchProgress] = useState<{ completed: number; total: number } | null>(null);
  const [platformChecks, setPlatformChecks] = useState<Record<string, boolean>>({
    youtube: true,
    tiktok: true,
    facebook: false,
    x: false,
  });
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, v] = await Promise.all([getStats(), getVideos()]);
      setStats(s);
      setVideos(v.videos);
    } catch {
      // API not available
    }
    // Fetch pipeline history
    try {
      const res = await fetch(`${BASE}/pipeline/history?limit=50`);
      if (res.ok) {
        const data = await res.json();
        setHistory(data);
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

  // Merge videos + history for the pipeline table
  const tableRows = history.length > 0 ? history : videos.map((v) => ({
    video_id: v.video_id,
    url: v.source_url,
    status: v.status,
    completed_stages: [] as string[],
    platforms: [] as string[],
    error: null as string | null,
    created_at: '',
    updated_at: '',
  }));

  const filteredRows = tableRows.filter((r) => {
    if (activeTab === 'All') return true;
    if (activeTab === 'Completed') return r.status === 'done' || r.status === 'transcribed' || r.status === 'processed';
    if (activeTab === 'Failed') return r.status === 'failed';
    if (activeTab === 'Running') return ['downloading', 'transcribing', 'processing', 'uploading', 'pending'].includes(r.status);
    return true;
  });

  const selectedPlatforms = Object.entries(platformChecks).filter(([, v]) => v).map(([k]) => k);

  const handleQuickProcess = async () => {
    if (!quickUrl.trim() || quickDownloading) return;
    setQuickDownloading(true);
    try {
      const res = await fetch(`${BASE}/pipeline/full`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: quickUrl.trim(),
          platforms: selectedPlatforms,
        }),
      });
      const data = await res.json();
      if (data.task_id) {
        subscribeSSE(data.task_id, (eventType) => {
          if (eventType === 'complete' || eventType === 'error') {
            setQuickDownloading(false);
            setQuickUrl('');
            refresh();
          }
        });
      }
    } catch {
      setQuickDownloading(false);
    }
  };

  const handleBatchProcess = async () => {
    const urls = batchUrls.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('#'));
    if (urls.length === 0 || batchRunning) return;
    setBatchRunning(true);
    setBatchProgress({ completed: 0, total: urls.length });
    try {
      const res = await fetch(`${BASE}/pipeline/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          urls,
          platforms: selectedPlatforms,
          concurrency: batchConcurrency,
        }),
      });
      const data = await res.json();
      if (data.batch_id) {
        subscribeSSE(data.batch_id, (eventType, eventData) => {
          if (eventType === 'progress') {
            setBatchProgress({
              completed: (eventData as { completed: number }).completed ?? 0,
              total: urls.length,
            });
          }
          if (eventType === 'complete' || eventType === 'error') {
            setBatchRunning(false);
            setBatchProgress(null);
            setBatchUrls('');
            refresh();
          }
        });
      }
    } catch {
      setBatchRunning(false);
      setBatchProgress(null);
    }
  };

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
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
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
            <span className="text-xs text-on-surface-variant font-medium uppercase tracking-wider">Success Rate</span>
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-mono font-semibold text-on-surface">{stats.successRate}%</span>
              <div className="flex gap-0.5">
                <div className="w-1 h-3 bg-emerald-500/40 rounded-full"></div>
                <div className="w-1 h-4 bg-emerald-500/60 rounded-full"></div>
                <div className="w-1 h-5 bg-emerald-500 rounded-full"></div>
              </div>
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

        {/* Middle Section */}
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Pipeline Table (60%) */}
          <div className="lg:w-[60%] space-y-4">
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
                    <th className="px-4 py-3 font-semibold">Video</th>
                    <th className="px-4 py-3 font-semibold text-center">Stages</th>
                    <th className="px-4 py-3 font-semibold">Platforms</th>
                    <th className="px-4 py-3 font-semibold">Started</th>
                    <th className="px-4 py-3 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody className="text-xs">
                  {filteredRows.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-zinc-500">
                        {tableRows.length === 0 ? 'No pipeline runs yet.' : 'No runs match this filter.'}
                      </td>
                    </tr>
                  ) : (
                    filteredRows.slice(0, 20).map((row) => {
                      const stages = stageFromStatus(row.status);
                      const isExpanded = expandedRow === row.video_id;
                      return (
                        <>
                          <tr
                            key={row.video_id}
                            onClick={() => setExpandedRow(isExpanded ? null : row.video_id)}
                            className="hover:bg-surface-container-high/50 transition-colors cursor-pointer group"
                          >
                            <td className="px-4 py-3">
                              <div className="flex flex-col">
                                <span className="font-medium text-on-surface line-clamp-1">
                                  {row.video_id.slice(0, 12)}
                                </span>
                                <span className="font-mono text-[9px] text-on-surface-variant">
                                  {row.url ? row.url.slice(0, 30) + '...' : ''}
                                </span>
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex justify-center gap-1.5" title={stageLabels.join(' → ')}>
                                {stages.map((s, i) => (
                                  <div key={i} className={`w-2 h-2 rounded-full ${stageDotColor(s)}`} title={stageLabels[i]} />
                                ))}
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex gap-1">
                                {(row.platforms || []).map((p) => (
                                  <span key={p} className="text-[9px] font-mono bg-surface-container-highest px-1.5 py-0.5 rounded">
                                    {p}
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td className="px-4 py-3 text-on-surface-variant font-mono text-[10px]">
                              {relativeTime(row.created_at)}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex gap-2">
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    navigate(`/videos/${row.video_id}`);
                                  }}
                                  className="text-[10px] text-primary hover:underline font-bold uppercase"
                                >
                                  View
                                </button>
                                {row.status === 'failed' && (
                                  <button
                                    onClick={async (e) => {
                                      e.stopPropagation();
                                      // Find the task_id or retry via video state
                                      try {
                                        await fetch(`${BASE}/pipeline/full`, {
                                          method: 'POST',
                                          headers: { 'Content-Type': 'application/json' },
                                          body: JSON.stringify({
                                            url: row.url,
                                            platforms: row.platforms,
                                            force: true,
                                          }),
                                        });
                                        refresh();
                                      } catch { /* ignore */ }
                                    }}
                                    className="text-[10px] text-error hover:underline font-bold uppercase"
                                  >
                                    Retry
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr key={`${row.video_id}-detail`}>
                              <td colSpan={5} className="px-6 py-3 bg-surface-container-lowest">
                                <div className="grid grid-cols-2 gap-3 text-[11px]">
                                  <div>
                                    <span className="text-on-surface-variant font-mono uppercase text-[9px]">Completed Stages</span>
                                    <p className="text-on-surface">{(row.completed_stages || []).join(' → ') || 'none'}</p>
                                  </div>
                                  <div>
                                    <span className="text-on-surface-variant font-mono uppercase text-[9px]">Status</span>
                                    <p className={row.status === 'failed' ? 'text-error' : 'text-on-surface'}>{row.status}</p>
                                  </div>
                                  {row.error && (
                                    <div className="col-span-2">
                                      <span className="text-on-surface-variant font-mono uppercase text-[9px]">Error</span>
                                      <p className="text-error font-mono text-[10px]">{row.error}</p>
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </>
                      );
                    })
                  )}
                </tbody>
              </table>
              <div className="p-3 border-t border-outline-variant/10 flex justify-between items-center">
                <span className="text-[10px] font-mono text-on-surface-variant">
                  Showing {Math.min(filteredRows.length, 20)} of {filteredRows.length} results
                </span>
              </div>
            </div>
          </div>

          {/* Quick Actions (40%) */}
          <div className="lg:w-[40%] space-y-6">
            {/* Quick Process */}
            <div className="bg-surface-container-low p-5 rounded-lg space-y-4">
              <h3 className="text-xs uppercase tracking-widest font-bold text-primary">Quick Process</h3>
              <div className="space-y-3">
                <div className="space-y-1">
                  <label className="text-[10px] text-on-surface-variant font-mono uppercase">Source URL</label>
                  <div className="flex gap-2">
                    <input
                      className="flex-1 bg-surface-container-lowest border-none rounded-md px-3 py-2 text-xs focus:ring-1 focus:ring-primary placeholder:text-zinc-600"
                      placeholder="https://v.douyin.com/..."
                      type="text"
                      value={quickUrl}
                      onChange={(e) => setQuickUrl(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleQuickProcess()}
                    />
                    <button
                      onClick={handleQuickProcess}
                      disabled={quickDownloading || !quickUrl.trim()}
                      className="px-4 py-2 main-button-gradient text-on-primary-fixed text-xs font-bold rounded-md disabled:opacity-50"
                    >
                      {quickDownloading ? '...' : 'GO'}
                    </button>
                  </div>
                </div>
                {/* Platform checkboxes */}
                <div className="flex flex-wrap gap-3">
                  {Object.entries(platformChecks).map(([plat, checked]) => (
                    <label key={plat} className="flex items-center gap-1.5 text-[10px] font-mono uppercase cursor-pointer">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => setPlatformChecks((prev) => ({ ...prev, [plat]: e.target.checked }))}
                        className="accent-primary w-3 h-3"
                      />
                      <span className={checked ? 'text-on-surface' : 'text-zinc-500'}>{plat}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>

            {/* Batch Process */}
            <div className="bg-surface-container-low p-5 rounded-lg space-y-4">
              <h3 className="text-xs uppercase tracking-widest font-bold text-primary">Batch Process</h3>
              <div className="space-y-3">
                <div className="space-y-1">
                  <label className="text-[10px] text-on-surface-variant font-mono uppercase">
                    URLs (one per line)
                    <span className="text-zinc-500 ml-2">
                      {batchUrls.split('\n').filter((l) => l.trim()).length} URLs
                    </span>
                  </label>
                  <textarea
                    className="w-full bg-surface-container-lowest border-none rounded-md px-3 py-2 text-xs focus:ring-1 focus:ring-primary placeholder:text-zinc-600 resize-none font-mono"
                    placeholder="https://v.douyin.com/xxx&#10;https://v.douyin.com/yyy&#10;https://v.douyin.com/zzz"
                    rows={4}
                    value={batchUrls}
                    onChange={(e) => setBatchUrls(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between text-[10px] font-mono uppercase">
                    <span className="text-on-surface-variant">Concurrency</span>
                    <span className="text-primary">{batchConcurrency} Workers</span>
                  </div>
                  <input
                    className="w-full accent-primary h-1 bg-surface-container-lowest rounded-lg appearance-none cursor-pointer"
                    type="range"
                    min={1}
                    max={5}
                    value={batchConcurrency}
                    onChange={(e) => setBatchConcurrency(Number(e.target.value))}
                  />
                </div>
                {batchProgress && (
                  <div className="space-y-1">
                    <div className="text-[10px] font-mono text-primary">
                      Processing {batchProgress.completed}/{batchProgress.total} videos...
                    </div>
                    <div className="w-full h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary transition-all duration-300"
                        style={{ width: `${(batchProgress.completed / batchProgress.total) * 100}%` }}
                      />
                    </div>
                  </div>
                )}
                <button
                  onClick={handleBatchProcess}
                  disabled={batchRunning || !batchUrls.trim()}
                  className="w-full py-2 bg-surface-container-high border border-outline-variant/20 hover:border-primary/50 text-on-surface text-xs font-bold rounded-md transition-colors disabled:opacity-50"
                >
                  {batchRunning ? 'PROCESSING...' : 'PROCESS ALL'}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Activity Feed — from pipeline history */}
        <div className="space-y-4">
          <h2 className="text-title-sm font-semibold text-on-surface">Recent Activity</h2>
          <div className="bg-surface-container-low rounded-lg p-2 space-y-1">
            {history.length === 0 && videos.length === 0 ? (
              <div className="px-4 py-4 text-center text-zinc-500 text-xs">No activity yet</div>
            ) : (
              [...history.slice(0, 20)].map((entry, i) => {
                const icon = entry.status === 'done' ? 'check_circle' : entry.status === 'failed' ? 'error' : 'pending';
                const color = entry.status === 'done' ? 'text-emerald-500' : entry.status === 'failed' ? 'text-error' : 'text-primary';
                return (
                  <div key={`${entry.video_id}-${i}`} className="flex items-center gap-4 px-4 py-2 hover:bg-surface-container-high/40 transition-colors">
                    <span className="font-mono text-[9px] text-zinc-600">{relativeTime(entry.updated_at)}</span>
                    <span className={`material-symbols-outlined text-sm ${color}`}>{icon}</span>
                    <span className="text-[11px] text-on-surface">
                      <span className="font-mono font-bold">{entry.video_id.slice(0, 10)}</span>
                      {' — '}
                      {entry.status === 'done'
                        ? `Completed for ${(entry.platforms || []).join(', ')}`
                        : entry.status === 'failed'
                          ? `Failed: ${entry.error?.slice(0, 60) || 'unknown'}`
                          : `${entry.status} (${(entry.completed_stages || []).join(', ')})`}
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
