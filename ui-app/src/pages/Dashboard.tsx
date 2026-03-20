import { useState, useEffect, useCallback } from 'react';
import { TopBar } from '../components/TopBar';
import { getStats, getVideos, postDownload, subscribeSSE } from '../api/client';
import type { DashboardStats, VideoMetadata } from '../api/types';
import { activityFeed } from '../data/mockData';

const filterTabs = ['All', 'Running', 'Completed', 'Failed'] as const;

function stageFromStatus(status: string): ('done' | 'active' | 'pending' | 'failed')[] {
  switch (status) {
    case 'transcribed':
      return ['done', 'done', 'pending', 'pending'];
    case 'downloaded':
      return ['done', 'pending', 'pending', 'pending'];
    case 'failed':
      return ['failed', 'pending', 'pending', 'pending'];
    default:
      return ['pending', 'pending', 'pending', 'pending'];
  }
}

function timeAgo(video: VideoMetadata): string {
  // Use video_id as a rough proxy — real timestamps would come from a DB
  return 'recent';
}

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<string>('All');
  const [stats, setStats] = useState<DashboardStats>({
    totalVideos: 0,
    processedToday: 0,
    successRate: 100,
    activeTasks: 0,
  });
  const [videos, setVideos] = useState<VideoMetadata[]>([]);
  const [quickUrl, setQuickUrl] = useState('');
  const [quickDownloading, setQuickDownloading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [s, v] = await Promise.all([getStats(), getVideos()]);
      setStats(s);
      setVideos(v.videos);
    } catch {
      // API not available
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const filteredVideos = videos.filter((v) => {
    if (activeTab === 'All') return true;
    if (activeTab === 'Completed') return v.status === 'transcribed';
    if (activeTab === 'Failed') return v.status === 'failed';
    if (activeTab === 'Running') return v.status === 'downloading' || v.status === 'transcribing';
    return true;
  });

  const handleQuickProcess = async () => {
    if (!quickUrl.trim() || quickDownloading) return;
    setQuickDownloading(true);
    try {
      const { task_id } = await postDownload(quickUrl.trim());
      subscribeSSE(task_id, (eventType) => {
        if (eventType === 'complete' || eventType === 'error') {
          setQuickDownloading(false);
          setQuickUrl('');
          refresh();
        }
      });
    } catch {
      setQuickDownloading(false);
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

  const feedLevelDot = (level: string) => {
    switch (level) {
      case 'info':
        return 'bg-primary/40';
      case 'success':
        return 'bg-emerald-500/40';
      case 'error':
        return 'bg-error/40';
      default:
        return 'bg-zinc-700';
    }
  };

  const feedLabelClass = (level: string) => {
    switch (level) {
      case 'info':
        return 'font-mono font-bold text-primary';
      case 'success':
        return 'font-mono font-bold text-emerald-500';
      case 'error':
        return 'font-mono font-bold text-error';
      default:
        return '';
    }
  };

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
            </div>
          </div>
          <div className="bg-surface-container-low p-4 rounded-lg flex flex-col gap-1 group hover:bg-surface-container transition-colors">
            <span className="text-xs text-on-surface-variant font-medium uppercase tracking-wider">Processed Today</span>
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-mono font-semibold text-on-surface">{stats.processedToday}</span>
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
                    <th className="px-4 py-3 font-semibold">Thumbnail &amp; Title</th>
                    <th className="px-4 py-3 font-semibold text-center">Pipeline</th>
                    <th className="px-4 py-3 font-semibold">Status</th>
                    <th className="px-4 py-3 font-semibold">Size</th>
                  </tr>
                </thead>
                <tbody className="text-xs">
                  {filteredVideos.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-4 py-8 text-center text-zinc-500">
                        {videos.length === 0 ? 'No videos yet. Download one to get started.' : 'No videos match this filter.'}
                      </td>
                    </tr>
                  ) : (
                    filteredVideos.map((v) => {
                      const stages = stageFromStatus(v.status);
                      return (
                        <tr key={v.video_id} className="hover:bg-surface-container-high/50 transition-colors group">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3">
                              <div className="w-12 h-8 rounded bg-surface-container-highest overflow-hidden relative flex items-center justify-center">
                                <span className="material-symbols-outlined text-xs text-zinc-600">movie</span>
                              </div>
                              <div className="flex flex-col">
                                <span className="font-medium text-on-surface line-clamp-1">
                                  {v.title || `${v.video_id}.mp4`}
                                </span>
                                <span className="font-mono text-[9px] text-on-surface-variant uppercase">
                                  ID: {v.video_id.slice(0, 8)}
                                </span>
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex justify-center gap-1.5">
                              {stages.map((s, i) => (
                                <div key={i} className={`w-2 h-2 rounded-full ${stageDotColor(s)}`} />
                              ))}
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className={`text-[10px] font-bold uppercase ${
                                v.status === 'transcribed'
                                  ? 'text-emerald-500'
                                  : v.status === 'downloaded'
                                    ? 'text-primary'
                                    : 'text-error'
                              }`}
                            >
                              {v.status}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className="font-mono text-on-surface-variant">{v.size}</span>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
              <div className="p-3 border-t border-outline-variant/10 flex justify-between items-center">
                <span className="text-[10px] font-mono text-on-surface-variant">
                  Showing {filteredVideos.length} of {videos.length} results
                </span>
              </div>
            </div>
          </div>

          {/* Quick Actions (40%) */}
          <div className="lg:w-[40%] space-y-6">
            <div className="bg-surface-container-low p-5 rounded-lg space-y-4">
              <h3 className="text-xs uppercase tracking-widest font-bold text-primary">Quick Process</h3>
              <div className="space-y-2">
                <label className="text-[10px] text-on-surface-variant font-mono uppercase">Single Source URL</label>
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
                    {quickDownloading ? '...' : 'START'}
                  </button>
                </div>
              </div>
            </div>
            <div className="bg-surface-container-low p-5 rounded-lg space-y-4">
              <h3 className="text-xs uppercase tracking-widest font-bold text-primary">Batch Engine</h3>
              <div className="space-y-3">
                <div className="space-y-1">
                  <label className="text-[10px] text-on-surface-variant font-mono uppercase">URL List (New line separated)</label>
                  <textarea
                    className="w-full bg-surface-container-lowest border-none rounded-md px-3 py-2 text-xs focus:ring-1 focus:ring-primary placeholder:text-zinc-600 resize-none"
                    placeholder="Paste multiple links here..."
                    rows={4}
                  ></textarea>
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between text-[10px] font-mono uppercase">
                    <span className="text-on-surface-variant">Concurrency Limit</span>
                    <span className="text-primary">4 Workers</span>
                  </div>
                  <input
                    className="w-full accent-primary h-1 bg-surface-container-lowest rounded-lg appearance-none cursor-pointer"
                    type="range"
                  />
                </div>
                <button className="w-full py-2 bg-surface-container-high border border-outline-variant/20 hover:border-primary/50 text-on-surface text-xs font-bold rounded-md transition-colors">
                  INITIATE BATCH QUEUE
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Activity Feed (mock for Phase 1) */}
        <div className="space-y-4">
          <h2 className="text-title-sm font-semibold text-on-surface">System Activity Feed</h2>
          <div className="bg-surface-container-low rounded-lg p-2 space-y-1">
            {activityFeed.map((event, i) => (
              <div key={i} className="flex items-center gap-4 px-4 py-2 hover:bg-surface-container-high/40 transition-colors">
                <span className="font-mono text-[9px] text-zinc-600">{event.time}</span>
                <div className={`w-1.5 h-1.5 rounded-full ${feedLevelDot(event.level)}`}></div>
                <span className="text-[11px] text-on-surface">
                  {event.label && <span className={feedLabelClass(event.level)}>{event.label} </span>}
                  {event.message}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
