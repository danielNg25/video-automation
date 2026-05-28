import { useState } from 'react';
import { cancelTask } from '../../api/client';
import type { CancelTaskResponse } from '../../api/client';

interface Props {
  taskId: string;
  /** When set and > 1, modal text reads "Stop this batch?" with the count. */
  count?: number;
  /** Called after the cancel API call returns. */
  onCancelled?: (response: CancelTaskResponse) => void;
}

export function StopButton({ taskId, count, onCancelled }: Props) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isBatch = (count ?? 1) > 1;

  const handleConfirm = async () => {
    setCancelling(true);
    setError(null);
    try {
      const result = await cancelTask(taskId);
      setConfirmOpen(false);
      onCancelled?.(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Cancel failed');
    } finally {
      setCancelling(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setConfirmOpen(true)}
        disabled={cancelling}
        className="px-2 py-1 text-[10px] font-mono uppercase tracking-tighter font-bold text-amber-400 hover:text-amber-300 border border-amber-500/30 hover:border-amber-500/60 rounded transition-colors"
      >
        {cancelling ? 'Stopping…' : '⊗ Stop'}
      </button>
      {confirmOpen && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
          onClick={() => !cancelling && setConfirmOpen(false)}
        >
          <div
            className="bg-surface-container-low rounded-xl p-6 max-w-md mx-4 border border-outline-variant/20"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-bold uppercase tracking-widest mb-3 text-on-surface">
              {isBatch ? 'Stop this batch?' : 'Stop this pipeline?'}
            </h3>
            <p className="text-xs text-on-surface-variant mb-5 leading-relaxed">
              {isBatch
                ? `${count} videos in progress will be discarded, and any downloaded / transcribed / generated files will be deleted.`
                : "All progress will be discarded and any downloaded / transcribed / generated files will be deleted."}
              {' '}
              <span className="text-amber-400 font-bold">This can't be undone.</span>
            </p>
            {error && (
              <p className="text-xs text-red-400 font-mono mb-3">{error}</p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                disabled={cancelling}
                className="px-4 py-2 text-xs font-bold uppercase tracking-widest text-on-surface-variant hover:text-on-surface transition-colors"
              >
                Keep going
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={cancelling}
                className="px-4 py-2 text-xs font-bold uppercase tracking-widest bg-amber-500/80 hover:bg-amber-500 text-on-primary-fixed rounded transition-colors disabled:opacity-50"
              >
                {cancelling ? 'Stopping…' : 'Stop and delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
