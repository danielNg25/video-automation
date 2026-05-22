import { useEffect, useState } from 'react';
import { getConfig, putConfig } from '../../api/client';

export function PipelineSection() {
  const [pipelineDataDir, setPipelineDataDir] = useState('data');
  const [pipelineMaxConcurrent, setPipelineMaxConcurrent] = useState(3);
  const [pipelineRetryAttempts, setPipelineRetryAttempts] = useState(3);
  const [pipelineRetryDelay, setPipelineRetryDelay] = useState(10);
  const [skipExisting, setSkipExisting] = useState(true);
  const [saveMsg, setSaveMsg] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!saveMsg) return;
    const t = setTimeout(() => setSaveMsg(''), 2000);
    return () => clearTimeout(t);
  }, [saveMsg]);

  useEffect(() => {
    getConfig().then((cfg) => {
      const p = (cfg.pipeline || {}) as Record<string, unknown>;
      if (p.data_dir) setPipelineDataDir(String(p.data_dir));
      if (p.max_concurrent) setPipelineMaxConcurrent(Number(p.max_concurrent));
      if (p.retry_attempts) setPipelineRetryAttempts(Number(p.retry_attempts));
      if (p.retry_delay) setPipelineRetryDelay(Number(p.retry_delay));
      if (p.skip_existing !== undefined) setSkipExisting(Boolean(p.skip_existing));
    }).catch(() => {});
  }, []);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await putConfig({
        pipeline: {
          data_dir: pipelineDataDir,
          max_concurrent: pipelineMaxConcurrent,
          retry_attempts: pipelineRetryAttempts,
          retry_delay: pipelineRetryDelay,
          skip_existing: skipExisting,
        },
      });
      setSaveMsg('Saved.');
    } catch (e) {
      setSaveMsg(`Save failed: ${e instanceof Error ? e.message : 'unknown error'}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section className="space-y-6" id="pipeline">
      <div className="border-b border-zinc-800/30 pb-4">
        <h2 className="text-xl font-semibold text-on-surface">Pipeline</h2>
        <p className="text-xs text-on-surface-variant font-mono mt-1 opacity-70">Batch processing and concurrency management.</p>
      </div>
      <div className="space-y-6">
        <div className="space-y-2">
          <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Data Directory</label>
          <div className="flex gap-2">
            <input className="flex-1 bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="text" value={pipelineDataDir} onChange={(e) => setPipelineDataDir(e.target.value)} />
            <button className="px-4 py-2 bg-surface-container-high hover:bg-surface-variant transition-colors rounded">
              <span className="material-symbols-outlined text-zinc-400">folder_open</span>
            </button>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Max Concurrent</label>
            <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="number" min={1} max={10} value={pipelineMaxConcurrent} onChange={(e) => setPipelineMaxConcurrent(Number(e.target.value))} />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Retry Attempts</label>
            <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="number" min={1} max={5} value={pipelineRetryAttempts} onChange={(e) => setPipelineRetryAttempts(Number(e.target.value))} />
          </div>
          <div className="space-y-2">
            <label className="text-xs font-bold uppercase tracking-widest text-zinc-500">Retry Delay (s)</label>
            <input className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-3 text-sm font-mono" type="number" min={1} max={120} value={pipelineRetryDelay} onChange={(e) => setPipelineRetryDelay(Number(e.target.value))} />
          </div>
        </div>
        <div className="flex items-center justify-between p-4 bg-primary-container/10 rounded-lg border border-primary/20">
          <div>
            <h4 className="text-sm font-semibold text-primary">Skip Existing Files</h4>
            <p className="text-[11px] text-zinc-500 mt-0.5">Resume tasks by checking for output fingerprints before starting compute.</p>
          </div>
          <div className="relative inline-flex items-center cursor-pointer">
            <input
              checked={skipExisting}
              onChange={(e) => setSkipExisting(e.target.checked)}
              className="sr-only peer"
              type="checkbox"
            />
            <div className="w-11 h-6 bg-surface-container-highest peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3 pt-2">
        <button
          disabled={isSaving}
          onClick={handleSave}
          className="px-6 py-2.5 bg-primary text-on-primary-fixed text-xs font-bold uppercase tracking-widest rounded disabled:opacity-40 transition-all"
        >
          {isSaving ? 'Saving...' : 'Save Pipeline Settings'}
        </button>
        {saveMsg && (
          <span className={`text-xs font-mono ${saveMsg.toLowerCase().startsWith('save failed') || saveMsg.toLowerCase().includes('error') ? 'text-red-400' : 'text-emerald-400'}`}>
            {saveMsg}
          </span>
        )}
      </div>
    </section>
  );
}
