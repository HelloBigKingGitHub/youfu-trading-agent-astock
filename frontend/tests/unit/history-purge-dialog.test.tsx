/**
 * P2.30 — Tests for the shared `HistoryPurgeDialog`.
 *
 * The dialog backs the destructive "清空所有历史" action on both the
 * dedicated `/history` page and the `/analyze` history tab.  These tests
 * pin the contract:
 *
 *   * Trigger button is visible and labeled correctly.
 *   * Confirmation text "清空" must be typed before the destructive action
 *     is enabled — a guard against fat-finger.
 *   * Pending state disables every interactive element so a double-click
 *     can't fire two requests.
 *   * Success → React Query invalidation for `['history']` /
 *     `['analyze-recent']`, removal of `['history-detail']` /
 *     `['analyze-progress']` / `['analyze-report']`, success toast, and
 *     the `onPurged` callback for page-local state reset.
 *   * 409 (active analyses) shows the user-readable reason + active count
 *     and keeps the dialog open so the user can retry later.
 *   * Generic error shows an error toast and keeps the dialog open.
 *   * Keyboard Escape cancels without submitting.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/ui/toast';

const mocks = vi.hoisted(() => ({
  purgeImpl: vi.fn(),
  invalidateQueries: vi.fn(),
  removeQueries: vi.fn(),
  onPurged: vi.fn(),
}));

vi.mock('@/api/history', async () => {
  const actual = await vi.importActual<typeof import('@/api/history')>('@/api/history');
  return {
    ...actual,
    purgeHistory: (...args: Parameters<typeof actual.purgeHistory>) =>
      mocks.purgeImpl(...args),
  };
});

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>(
    '@tanstack/react-query'
  );
  return {
    ...actual,
    useMutation: (config: {
      mutationFn: (input: { include_cache: boolean }) => Promise<unknown>;
      onSuccess?: (data: unknown) => void;
      onError?: (err: Error) => void;
    }) => {
      const state = {
        isPending: false,
        variables: undefined as unknown,
        mutate: async (input: { include_cache: boolean }) => {
          try {
            const data = await config.mutationFn(input);
            config.onSuccess?.(data);
          } catch (e) {
            config.onError?.(e as Error);
          }
        },
      };
      return state;
    },
    useQueryClient: () => ({
      invalidateQueries: mocks.invalidateQueries,
      removeQueries: mocks.removeQueries,
    }),
  };
});

import { HistoryPurgeDialog } from '@/components/history/history-purge-dialog';

function renderDialog() {
  return render(
    <ToastProvider>
      <HistoryPurgeDialog onPurged={mocks.onPurged} />
    </ToastProvider>
  );
}

describe('HistoryPurgeDialog', () => {
  beforeEach(() => {
    mocks.purgeImpl.mockReset();
    mocks.invalidateQueries.mockReset();
    mocks.removeQueries.mockReset();
    mocks.onPurged.mockReset();
    // Default: 200 happy path with sample counts.
    mocks.purgeImpl.mockResolvedValue({
      ok: true,
      history_deleted: 5,
      reports_deleted: 4,
      log_runs_deleted: 3,
      cache_files_deleted: 12,
      bytes_freed: 12345,
      failed_items: 0,
    });
  });

  it('renders the trigger button and starts with a closed dialog', () => {
    renderDialog();

    const trigger = screen.getByTestId('history-purge-trigger');
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveTextContent(/清空所有历史/);
    // No dialog content until clicked.
    expect(screen.queryByTestId('history-purge-dialog')).not.toBeInTheDocument();
  });

  it('opens the dialog with the destructive summary when the trigger is clicked', () => {
    renderDialog();

    fireEvent.click(screen.getByTestId('history-purge-trigger'));

    const dialog = screen.getByTestId('history-purge-dialog');
    expect(dialog).toBeInTheDocument();
    // Lists what WILL be wiped…
    expect(screen.getByText(/分析历史元数据/)).toBeInTheDocument();
    expect(screen.getByText(/生成报告/)).toBeInTheDocument();
    expect(screen.getByText(/行情缓存/)).toBeInTheDocument();
    // …and what will NOT be touched — each line is asserted separately so
    // a global regex won't double-match across sibling <li>s.
    expect(screen.getByText(/定时任务/)).toBeInTheDocument();
    expect(screen.getByText(/持仓/)).toBeInTheDocument();
    expect(screen.getByText(/自选股/)).toBeInTheDocument();
    expect(screen.getByText(/系统设置/)).toBeInTheDocument();

    // The destructive confirm is disabled until the user types the sentinel.
    const confirm = screen.getByTestId('history-purge-confirm');
    expect(confirm).toBeDisabled();
  });

  it('keeps the confirm button disabled when the typed text does not match 清空', () => {
    renderDialog();
    fireEvent.click(screen.getByTestId('history-purge-trigger'));

    const input = screen.getByTestId('history-purge-input');
    fireEvent.change(input, { target: { value: '清' } });
    expect(screen.getByTestId('history-purge-confirm')).toBeDisabled();

    fireEvent.change(input, { target: { value: '清空全部' } });
    expect(screen.getByTestId('history-purge-confirm')).toBeDisabled();
  });

  it('enables the confirm button once the user types exactly 清空', () => {
    renderDialog();
    fireEvent.click(screen.getByTestId('history-purge-trigger'));

    fireEvent.change(screen.getByTestId('history-purge-input'), {
      target: { value: '清空' },
    });
    expect(screen.getByTestId('history-purge-confirm')).toBeEnabled();
  });

  it('submits exactly once on success and triggers cache invalidation + onPurged', async () => {
    renderDialog();
    fireEvent.click(screen.getByTestId('history-purge-trigger'));
    fireEvent.change(screen.getByTestId('history-purge-input'), {
      target: { value: '清空' },
    });

    fireEvent.click(screen.getByTestId('history-purge-confirm'));

    await waitFor(() => {
      expect(mocks.purgeImpl).toHaveBeenCalledTimes(1);
    });
    // Confirmation token + include_cache are always sent.
    expect(mocks.purgeImpl).toHaveBeenCalledWith({
      confirmation: 'CLEAR_ALL_HISTORY',
      include_cache: true,
    });

    // React Query: invalidate history lists + remove per-id caches so a
    // stale detail/progress/report doesn't render post-purge.
    await waitFor(() => {
      const invocations = mocks.invalidateQueries.mock.calls.map(
        (c) => c[0] as { queryKey: readonly string[] }
      );
      const keys = invocations.map((c) => c.queryKey);
      expect(keys).toEqual(
        expect.arrayContaining([
          ['history'],
          ['analyze-recent'],
        ])
      );
    });
    await waitFor(() => {
      const removed = mocks.removeQueries.mock.calls.map(
        (c) => c[0] as { queryKey: readonly string[] }
      );
      const keys = removed.map((c) => c.queryKey);
      expect(keys).toEqual(
        expect.arrayContaining([
          ['history-detail'],
          ['analyze-progress'],
          ['analyze-report'],
        ])
      );
    });

    await waitFor(() => expect(mocks.onPurged).toHaveBeenCalledTimes(1));

    // Success toast surfaces the delete tally.
    await waitFor(() => {
      expect(screen.getByTestId('toast-success')).toBeInTheDocument();
    });
  });

  it('shows the active-analyses toast and keeps the dialog open on 409', async () => {
    const err = new Error(
      'POST /api/history/purge 409: {"detail":{"reason":"active_analyses","active_count":2,"active_ids":["a","b"]}}'
    );
    mocks.purgeImpl.mockRejectedValueOnce(err);

    renderDialog();
    fireEvent.click(screen.getByTestId('history-purge-trigger'));
    fireEvent.change(screen.getByTestId('history-purge-input'), {
      target: { value: '清空' },
    });
    fireEvent.click(screen.getByTestId('history-purge-confirm'));

    await waitFor(() => {
      expect(screen.getByTestId('toast-error')).toBeInTheDocument();
    });
    expect(screen.getByTestId('toast-error')).toHaveTextContent(/2/);
    // Dialog stays open so the user can retry after the runs finish.
    expect(screen.getByTestId('history-purge-dialog')).toBeInTheDocument();
    // onPurged is NOT called on failure.
    expect(mocks.onPurged).not.toHaveBeenCalled();
  });

  it('shows an error toast on generic failure and keeps the dialog open', async () => {
    mocks.purgeImpl.mockRejectedValueOnce(new Error('network down'));

    renderDialog();
    fireEvent.click(screen.getByTestId('history-purge-trigger'));
    fireEvent.change(screen.getByTestId('history-purge-input'), {
      target: { value: '清空' },
    });
    fireEvent.click(screen.getByTestId('history-purge-confirm'));

    await waitFor(() => {
      expect(screen.getByTestId('toast-error')).toBeInTheDocument();
    });
    expect(screen.getByTestId('toast-error')).toHaveTextContent(/network down/);
    expect(screen.getByTestId('history-purge-dialog')).toBeInTheDocument();
    expect(mocks.onPurged).not.toHaveBeenCalled();
  });

  it('Escape closes the dialog without submitting', async () => {
    renderDialog();
    fireEvent.click(screen.getByTestId('history-purge-trigger'));
    expect(screen.getByTestId('history-purge-dialog')).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });

    await waitFor(() =>
      expect(screen.queryByTestId('history-purge-dialog')).not.toBeInTheDocument()
    );
    expect(mocks.purgeImpl).not.toHaveBeenCalled();
  });

  it('falls back to the generic error toast when the 409 body is malformed', async () => {
    // 409 body missing ``active_count`` must NOT crash the toast renderer;
    // the runtime guard should treat it as a generic error instead of
    // rendering ``undefined`` slots in the template literal.
    const err = new Error(
      'POST /api/history/purge 409: {"detail":{"reason":"active_analyses","active_ids":["a"]}}'
    );
    mocks.purgeImpl.mockRejectedValueOnce(err);

    renderDialog();
    fireEvent.click(screen.getByTestId('history-purge-trigger'));
    fireEvent.change(screen.getByTestId('history-purge-input'), {
      target: { value: '清空' },
    });
    fireEvent.click(screen.getByTestId('history-purge-confirm'));

    await waitFor(() => {
      expect(screen.getByTestId('toast-error')).toBeInTheDocument();
    });
    // Generic error — no "当前 N 个分析..." prefix because the guard
    // refused to parse the malformed payload.
    expect(screen.getByTestId('toast-error')).toHaveTextContent(/POST \/api\/history\/purge 409/);
  });
});