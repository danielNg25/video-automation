import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePipelineRuns, relativeTime, stageFromStatus, type PipelineRun } from '../lib/usePipelineRuns';

const BASE = '/api';
const filterTabs = ['All', 'Running', 'Completed', 'Failed'] as const;
const MAX_VISIBLE = 10;

const stageDotColor = (stage: string) => {
  switch (stage) {
    case 'done': return 'bg-emerald-500';
    case 'active': return 'bg-primary animate-pulse';
    case 'failed': return 'bg-error';
    default: return 'bg-surface-container-highest';
  }
};

const stageLabels = ['Download', 'Transcribe', 'Process', 'Upload'];

export function PipelineRunsTable() {
  const navigate = useNavigate();
  const { runs, refresh } = usePipelineRuns();
  const [activeTab, setActiveTab] = useState<typeof filterTabs[number]>('All');
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const filteredRuns: PipelineRun[] = runs.filter((r) => {
    if (activeTab === 'All') return true;
    if (activeTab === 'Completed') return r.status === 'done' || r.status === 'skipped';
    if (activeTab === 'Failed') return r.status === 'failed';
    if (activeTab === 'Running') return r.status === 'running';
    return true;
  });

  const handleRetry = async (run: PipelineRun, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      if (run.mode === 'batch') {
        const failedUrls = run.errors.map((er) => er.url);
        await fetch(`${BASE}/pipeline/batch`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ urls: failedUrls, platforms: run.platforms, concurrency: 2, force: true }),
        });
      } else {
        await fetch(`${BASE}/pipeline/full`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: run.urls[0], platforms: run.platforms, force: true }),
        });
      }
      refresh();
    } catch { /* ignore */ }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-title-sm font-semibold text-on-surface">Recent Runs</h2>
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
              filteredRuns.slice(0, MAX_VISIBLE).map((run) => {
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
                              {isBatch ? `Batch · ${run.urls.length} videos` : (run.children[0]?.title || (run.urls[0] || '').slice(0, 35) + '...')}
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
                            <button
                              onClick={(e) => { e.stopPropagation(); navigate(`/videos/${run.video_ids[0]}`); }}
                              className="text-[10px] text-primary hover:underline font-bold uppercase"
                            >
                              View
                            </button>
                          )}
                          {run.status === 'failed' && (
                            <button
                              onClick={(e) => handleRetry(run, e)}
                              className="text-[10px] text-error hover:underline font-bold uppercase"
                            >
                              Retry
                            </button>
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
                                  <div
                                    key={child.video_id}
                                    className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-surface-container-low/50 cursor-pointer"
                                    onClick={(e) => { e.stopPropagation(); navigate(`/videos/${child.video_id}`); }}
                                  >
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
            Showing {Math.min(filteredRuns.length, MAX_VISIBLE)} of {filteredRuns.length} runs
          </span>
        </div>
      </div>
    </div>
  );
}
