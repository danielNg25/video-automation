/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

/** Canonical pipeline stage names — must match `STAGE_RANGES` keys in src/pipeline.py. */
export type PipelineStageName =
  | 'download'
  | 'transcribe'
  | 'translate'
  | 'tts'
  | 'process';

export const PIPELINE_STAGE_ORDER: PipelineStageName[] = [
  'download',
  'transcribe',
  'translate',
  'tts',
  'process',
];

export type PipelineRunStatus = 'idle' | 'running' | 'completed' | 'failed';

export type PipelineMode = 'single' | 'batch';

export type PipelineChild = {
  videoId: string;
  status: string;
  currentStage: string;
  stageProgress: number;
  progress: number;
  message: string;
  error: string | null;
};

export type PipelineStatus = {
  taskId: string | null;
  mode: PipelineMode | null;
  status: PipelineRunStatus;
  currentStage: PipelineStageName | '';
  stageProgress: number;       // 0..1, per-current-stage
  completedStages: PipelineStageName[];
  progress: number;            // 0..1 overall
  message: string;
  videoId: string | null;
  // Batch-only fields
  children: PipelineChild[];
  batchTotal: number;
  batchCompleted: number;
  error: string | null;
};

const IDLE_STATUS: PipelineStatus = {
  taskId: null,
  mode: null,
  status: 'idle',
  currentStage: '',
  stageProgress: 0,
  completedStages: [],
  progress: 0,
  message: '',
  videoId: null,
  children: [],
  batchTotal: 0,
  batchCompleted: 0,
  error: null,
};

const STORAGE_KEY = 'pipeline_active_task';
const POLL_INTERVAL_MS = 2000;

/** Subset of PipelineStatus persisted to sessionStorage for optimistic restore. */
type LastKnown = Pick<
  PipelineStatus,
  'currentStage' | 'stageProgress' | 'completedStages' | 'progress' | 'message'
>;

type StoredPayload = {
  taskId: string;
  mode: PipelineMode;
  lastKnown?: LastKnown;
};

const VALID_STAGES = new Set<string>(PIPELINE_STAGE_ORDER);

function isPipelineStageName(s: unknown): s is PipelineStageName {
  return typeof s === 'string' && VALID_STAGES.has(s);
}

function parseStoredPayload(raw: string | null): StoredPayload | null {
  if (!raw) return null;
  try {
    const obj = JSON.parse(raw);
    if (
      obj &&
      typeof obj.taskId === 'string' &&
      (obj.mode === 'single' || obj.mode === 'batch')
    ) {
      return obj as StoredPayload;
    }
  } catch {
    // fall through
  }
  return null;
}

function primedFromStored(stored: StoredPayload | null): PipelineStatus {
  if (!stored) return IDLE_STATUS;
  const lk = stored.lastKnown;
  return {
    ...IDLE_STATUS,
    taskId: stored.taskId,
    mode: stored.mode,
    status: 'running',
    currentStage: lk && isPipelineStageName(lk.currentStage) ? lk.currentStage : '',
    stageProgress: lk?.stageProgress ?? 0,
    completedStages:
      lk?.completedStages?.filter(isPipelineStageName) ?? [],
    progress: lk?.progress ?? 0,
    message: lk?.message ?? 'Resuming…',
  };
}

type ContextValue = {
  status: PipelineStatus;
  /** Start tracking a newly-launched task. Resets in-memory state. */
  startPolling: (taskId: string, mode: PipelineMode) => void;
  /** Stop polling and reset status to idle. */
  stopPolling: () => void;
};

const PipelineStatusContext = createContext<ContextValue>({
  status: IDLE_STATUS,
  startPolling: () => {},
  stopPolling: () => {},
});

export function usePipelineStatus(): ContextValue {
  return useContext(PipelineStatusContext);
}

export function PipelineStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<PipelineStatus>(() =>
    primedFromStored(parseStoredPayload(sessionStorage.getItem(STORAGE_KEY)))
  );
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const taskIdRef = useRef<string | null>(status.taskId);
  const modeRef = useRef<PipelineMode | null>(status.mode);

  const clearStored = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
  }, []);

  const persistStored = useCallback((s: PipelineStatus) => {
    if (!s.taskId || !s.mode || s.status !== 'running') return;
    const payload: StoredPayload = {
      taskId: s.taskId,
      mode: s.mode,
      lastKnown: {
        currentStage: s.currentStage,
        stageProgress: s.stageProgress,
        completedStages: s.completedStages,
        progress: s.progress,
        message: s.message,
      },
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }, []);

  const stopPollingInternal = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    taskIdRef.current = null;
    modeRef.current = null;
  }, []);

  const pollOnce = useCallback(async () => {
    const tid = taskIdRef.current;
    const mode = modeRef.current;
    if (!tid || !mode) return;
    try {
      const r = await fetch(`/api/pipeline/${tid}`);
      if (!r.ok) {
        stopPollingInternal();
        clearStored();
        setStatus(IDLE_STATUS);
        return;
      }
      const d = await r.json();
      if (mode === 'batch' && Array.isArray(d.children)) {
        const childrenRaw = d.children as Array<Record<string, unknown>>;
        const children: PipelineChild[] = childrenRaw.map((c) => ({
          videoId: String(c.video_id ?? ''),
          status: String(c.status ?? ''),
          currentStage: String(c.current_stage ?? ''),
          stageProgress: typeof c.stage_progress === 'number' ? c.stage_progress : 0,
          progress: typeof c.progress === 'number' ? c.progress : 0,
          message: String(c.message ?? ''),
          error: c.error == null ? null : String(c.error),
        }));
        const done = children.filter((c) => c.status === 'done' || c.status === 'failed').length;
        const total = children.length;
        const next: PipelineStatus = {
          ...IDLE_STATUS,
          taskId: tid,
          mode: 'batch',
          status:
            d.status === 'completed'
              ? 'completed'
              : d.status === 'failed'
                ? 'failed'
                : 'running',
          progress: total > 0 ? children.reduce((a, c) => a + c.progress, 0) / total : 0,
          message: typeof d.message === 'string' ? d.message : '',
          children,
          batchTotal: total,
          batchCompleted: done,
          error: d.error == null ? null : String(d.error),
        };
        setStatus(next);
        persistStored(next);
        if (next.status !== 'running') {
          stopPollingInternal();
          clearStored();
        }
        return;
      }
      // single-pipeline path
      const rawStage = String(d.current_stage ?? '');
      const currentStage: PipelineStageName | '' = isPipelineStageName(rawStage) ? rawStage : '';
      const completedStages = Array.isArray(d.completed_stages)
        ? (d.completed_stages as unknown[]).filter(isPipelineStageName)
        : [];
      const next: PipelineStatus = {
        ...IDLE_STATUS,
        taskId: tid,
        mode: 'single',
        status:
          d.status === 'completed'
            ? 'completed'
            : d.status === 'failed'
              ? 'failed'
              : 'running',
        currentStage,
        stageProgress: typeof d.stage_progress === 'number' ? d.stage_progress : 0,
        completedStages,
        progress: typeof d.progress === 'number' ? d.progress : 0,
        message: typeof d.message === 'string' ? d.message : '',
        videoId: typeof d.video_id === 'string' ? d.video_id : null,
        children: [],
        error: d.error == null ? null : String(d.error),
      };
      setStatus(next);
      persistStored(next);
      if (next.status !== 'running') {
        stopPollingInternal();
        clearStored();
      }
    } catch {
      // Network blip — keep polling on the next tick.
    }
  }, [clearStored, persistStored, stopPollingInternal]);

  const startPolling = useCallback(
    (taskId: string, mode: PipelineMode) => {
      stopPollingInternal();
      taskIdRef.current = taskId;
      modeRef.current = mode;
      const seed: PipelineStatus = {
        ...IDLE_STATUS,
        taskId,
        mode,
        status: 'running',
        message: 'Starting…',
      };
      setStatus(seed);
      persistStored(seed);
      pollRef.current = setInterval(pollOnce, POLL_INTERVAL_MS);
      // Fire immediately so the UI doesn't wait a full POLL_INTERVAL for the first update.
      void pollOnce();
    },
    [persistStored, pollOnce, stopPollingInternal]
  );

  const stopPolling = useCallback(() => {
    stopPollingInternal();
    clearStored();
    setStatus(IDLE_STATUS);
  }, [clearStored, stopPollingInternal]);

  // On mount: if sessionStorage has an active task, resume polling.
  useEffect(() => {
    const stored = parseStoredPayload(sessionStorage.getItem(STORAGE_KEY));
    if (stored) {
      taskIdRef.current = stored.taskId;
      modeRef.current = stored.mode;
      pollRef.current = setInterval(pollOnce, POLL_INTERVAL_MS);
      void pollOnce();
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <PipelineStatusContext.Provider value={{ status, startPolling, stopPolling }}>
      {children}
    </PipelineStatusContext.Provider>
  );
}
