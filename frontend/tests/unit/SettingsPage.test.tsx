import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/ui/toast';
import { SettingsPage } from '@/pages/SettingsPage';

const mocks = vi.hoisted(() => ({
  invalidateQueries: vi.fn(),
  mutate: vi.fn(),
  queryData: {
    settings: {
      provider: 'minimax',
      deepModel: 'MiniMax-M3',
      quickModel: 'MiniMax-M2.7-highspeed',
      apiKey: '',
      apiKeySet: false,
      baseUrl: '',
    },
    providers: [
      {
        key: 'minimax',
        label: 'MiniMax（推荐·国内直连）',
        deep: [{ label: 'MiniMax-M3', value: 'MiniMax-M3' }],
        quick: [{ label: 'MiniMax-M2.7-highspeed', value: 'MiniMax-M2.7-highspeed' }],
      },
      {
        key: 'deepseek',
        label: 'DeepSeek',
        deep: [{ label: 'deepseek-chat', value: 'deepseek-chat' }],
        quick: [{ label: 'deepseek-chat', value: 'deepseek-chat' }],
      },
    ],
  },
}));

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
  // Keep the mocked response reference stable.  SettingsPage copies server
  // values into local state in an effect; returning a fresh object each render
  // would continually reset values changed by fireEvent.
  useQuery: () => ({
    data: mocks.queryData,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    isFetching: false,
  }),
  useMutation: () => ({ isPending: false, mutate: mocks.mutate }),
}));

describe('SettingsPage', () => {
  beforeEach(() => {
    mocks.mutate.mockClear();
    mocks.invalidateQueries.mockClear();
  });

  function renderPage() {
    return render(
      <ToastProvider>
        <SettingsPage />
      </ToastProvider>,
    );
  }

  it('renders the provider, model, base URL fields, and save button', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByLabelText('LLM 供应商')).toHaveValue('minimax'));
    expect(screen.getByTestId('settings-form')).toBeInTheDocument();
    expect(screen.getByLabelText('LLM 供应商')).toHaveValue('minimax');
    expect(screen.getByLabelText('深度模型')).toHaveValue('MiniMax-M3');
    expect(screen.getByLabelText('快速模型')).toHaveValue('MiniMax-M2.7-highspeed');
    expect(screen.getByLabelText(/Base URL/)).toHaveValue('');
    expect(screen.getByRole('button', { name: /保存/ })).toBeInTheDocument();
  });

  it('submits changed form values through the React Query mutation', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByLabelText('LLM 供应商')).toHaveValue('minimax'));

    fireEvent.change(screen.getByLabelText('LLM 供应商'), { target: { value: 'deepseek' } });
    fireEvent.change(screen.getByLabelText(/Base URL/), {
      target: { value: 'https://gateway.example/v1' },
    });
    fireEvent.submit(screen.getByTestId('settings-form'));

    expect(mocks.mutate).toHaveBeenCalledWith({
      provider: 'deepseek',
      deepModel: 'deepseek-chat',
      quickModel: 'deepseek-chat',
      baseUrl: 'https://gateway.example/v1',
    });
  });

  it('resets edited values to the last server response', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByLabelText('LLM 供应商')).toHaveValue('minimax'));

    const baseUrl = screen.getByLabelText(/Base URL/);
    fireEvent.change(baseUrl, { target: { value: 'https://temporary.example/v1' } });
    expect(baseUrl).toHaveValue('https://temporary.example/v1');

    fireEvent.click(screen.getByRole('button', { name: /重置/ }));
    expect(baseUrl).toHaveValue('');
  });
});
