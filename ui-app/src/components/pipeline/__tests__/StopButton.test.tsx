import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StopButton } from '../StopButton';

// Mock the API call
vi.mock('../../../api/client', () => ({
  cancelTask: vi.fn(() => Promise.resolve({
    task_id: 't1',
    status: 'cancelled',
    cleaned: true,
    video_id: 'vid1',
  })),
}));

describe('StopButton', () => {
  it('renders the Stop label', () => {
    render(<StopButton taskId="t1" />);
    expect(screen.getByRole('button', { name: /stop/i })).toBeInTheDocument();
  });

  it('opens confirm modal on click, does not cancel immediately', async () => {
    const onCancelled = vi.fn();
    render(<StopButton taskId="t1" onCancelled={onCancelled} />);
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    // Modal opens
    expect(screen.getByText(/can't be undone/i)).toBeInTheDocument();
    // Callback NOT yet called
    expect(onCancelled).not.toHaveBeenCalled();
  });

  it('confirms and calls cancelTask + onCancelled', async () => {
    const { cancelTask } = await import('../../../api/client');
    const onCancelled = vi.fn();
    render(<StopButton taskId="t1" onCancelled={onCancelled} />);
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    // Click the confirm button in modal
    fireEvent.click(screen.getByRole('button', { name: /^stop and delete/i }));
    await waitFor(() => expect(cancelTask).toHaveBeenCalledWith('t1'));
    await waitFor(() => expect(onCancelled).toHaveBeenCalled());
  });

  it('shows custom batch text when count > 1', () => {
    render(<StopButton taskId="b1" count={3} />);
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    expect(screen.getByText(/3 videos in progress/i)).toBeInTheDocument();
  });
});
