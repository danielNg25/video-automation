import {
  PIPELINE_STAGE_ORDER,
  type PipelineStageName,
  type PipelineStatus,
} from '../lib/pipelineStatus';

const STAGE_LABELS: Record<PipelineStageName, string> = {
  download: 'Download',
  transcribe: 'Transcribe (OCR)',
  translate: 'Translate',
  tts: 'TTS Dubbing',
  process: 'Process & Burn',
};

type StageRowState = 'done' | 'running' | 'pending' | 'skipped';

function rowState(
  stage: PipelineStageName,
  status: PipelineStatus
): StageRowState {
  if (status.completedStages.includes(stage)) return 'done';
  if (status.currentStage === stage) return 'running';
  // Translate-skipped detection: currentStage has moved past translate
  // without translate appearing in completedStages.
  if (stage === 'translate') {
    const currentIdx = PIPELINE_STAGE_ORDER.indexOf(
      (status.currentStage || 'download') as PipelineStageName
    );
    const translateIdx = PIPELINE_STAGE_ORDER.indexOf('translate');
    if (
      currentIdx > translateIdx ||
      status.completedStages.some((s) => {
        const i = PIPELINE_STAGE_ORDER.indexOf(s);
        return i > translateIdx;
      })
    ) {
      return 'skipped';
    }
  }
  return 'pending';
}

function StageIcon({ state }: { state: StageRowState }) {
  if (state === 'done') {
    return (
      <div className="w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
        <span className="material-symbols-outlined text-sm">check</span>
      </div>
    );
  }
  if (state === 'running') {
    return (
      <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center shrink-0">
        <div className="w-3 h-3 rounded-full border-2 border-primary border-t-transparent animate-spin" />
      </div>
    );
  }
  if (state === 'skipped') {
    return (
      <div className="w-6 h-6 rounded-full bg-surface-container-highest text-zinc-600 flex items-center justify-center shrink-0">
        <span className="material-symbols-outlined text-sm">remove</span>
      </div>
    );
  }
  return (
    <div className="w-6 h-6 rounded-full border border-outline-variant/30 shrink-0" />
  );
}

function StageBar({
  state,
  stagePercent,
}: {
  state: StageRowState;
  stagePercent: number;
}) {
  const width =
    state === 'done' ? 100 : state === 'running' ? Math.round(stagePercent) : 0;
  const colorClass =
    state === 'done'
      ? 'bg-emerald-500/30'
      : state === 'running'
        ? 'bg-primary'
        : 'bg-surface-container-highest';
  return (
    <div className="w-full h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
      <div
        className={`h-full ${colorClass} transition-all duration-300`}
        style={{ width: `${width}%` }}
      />
    </div>
  );
}

export function PipelineStageTracker({ status }: { status: PipelineStatus }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-primary text-lg">
          account_tree
        </span>
        <span className="text-xs font-bold uppercase tracking-widest text-zinc-500">
          Pipeline running
        </span>
        <span className="ml-auto text-[10px] font-mono text-zinc-500">
          {Math.round((status.progress ?? 0) * 100)}% overall
        </span>
      </div>
      <div className="space-y-3">
        {PIPELINE_STAGE_ORDER.map((stage) => {
          const state = rowState(stage, status);
          const isRunning = state === 'running';
          const stagePercent = (status.stageProgress ?? 0) * 100;
          const labelClass =
            state === 'done'
              ? 'text-emerald-400'
              : state === 'running'
                ? 'text-on-surface'
                : state === 'skipped'
                  ? 'text-zinc-600 line-through'
                  : 'text-zinc-600';
          return (
            <div key={stage} className="flex items-start gap-3">
              <StageIcon state={state} />
              <div className="flex-1 min-w-0 space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className={`text-sm font-semibold ${labelClass}`}>
                    {STAGE_LABELS[stage]}
                  </span>
                  {state === 'running' && (
                    <span className="text-[10px] font-mono text-on-surface-variant">
                      {Math.round(stagePercent)}%
                    </span>
                  )}
                </div>
                <StageBar state={state} stagePercent={stagePercent} />
                {isRunning && status.message && (
                  <p className="text-[10px] font-mono text-on-surface-variant whitespace-pre-line">
                    {status.message}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
