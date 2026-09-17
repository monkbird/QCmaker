import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { forwardRef, useImperativeHandle } from 'react';
import { LegacyVisualizationPage as VisualizationPage } from '../pages/VisualizationPage';
import { generateChart, recommendChart } from '../api/visualization';
import { chartInsight } from '../api/insight';
import { loadDataset } from '../storage/db';

const wizard = vi.hoisted(() => ({ state: { currentProjectId: 'p', dataRef: 'a', datasetRevision: 1, topic: 'topic' }, setChart: vi.fn(), navigate: vi.fn() }));
vi.mock('../context/WizardContext', () => ({ useWizard: () => wizard }));
vi.mock('react-router', () => ({ useNavigate: () => wizard.navigate }));
vi.mock('../api/visualization', () => ({ generateChart: vi.fn(), recommendChart: vi.fn() }));
vi.mock('../api/insight', () => ({ chartInsight: vi.fn() }));
vi.mock('../storage/db', () => ({ loadDataset: vi.fn() }));
vi.mock('../components/StepPage', () => ({ StepPage: ({ actions, children }: { actions: React.ReactNode; children: React.ReactNode }) => <div>{actions}{children}</div> }));
vi.mock('echarts-for-react/lib/core', () => ({ default: forwardRef(function Chart({ option }: { option: unknown }, ref) { useImperativeHandle(ref, () => ({ getEchartsInstance: () => ({ getDataURL: () => 'data:image/png;base64,AA==' }) })); return <div data-testid="chart">{JSON.stringify(option)}</div>; }) }));
const chart = (name: string) => ({ option: { title: { text: name } }, processing: { aggregation: 'sum' as const, converted_row_ids: [], grouped_categories: 0, warnings: [] } });
const recommendation = { chart_type: 'line' as const, x_axis: 'name', y_axis: 'value', aggregation: 'sum' as const, reason: 'recommended' };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
const button = (name: string) => screen.getByRole('button', { name: new RegExp(name) });
beforeEach(() => {
  vi.clearAllMocks(); wizard.state = { currentProjectId: 'p', dataRef: 'a', datasetRevision: 1, topic: 'topic' };
  vi.mocked(loadDataset).mockResolvedValue({ dataset_id: 'a', revision: 1, filename: 'a', columns: [{ name: 'name', inferred_type: 'string' }, { name: 'value', inferred_type: 'number' }], rows: [], report: {} } as never);
  vi.mocked(generateChart).mockResolvedValue(chart('A')); vi.mocked(recommendChart).mockResolvedValue(recommendation);
});
afterEach(cleanup);
async function open() { const view = render(<VisualizationPage />); await waitFor(() => expect(button('规则推荐')).not.toBeDisabled()); return view; }

it.each(['规则推荐', 'AI 图表顾问'])('invalidates chart A when %s generates a replacement that fails', async name => {
  vi.mocked(chartInsight).mockResolvedValue({ recommendation, insight: 'new insight', caveats: [], model: 'test', source: 'ai' });
  await open(); fireEvent.click(button('生成预览')); await screen.findByTestId('chart');
  vi.mocked(generateChart).mockRejectedValueOnce(new Error('generation failed'));
  fireEvent.click(button(name));
  await waitFor(() => expect(generateChart).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(button('规则推荐')).not.toBeDisabled());
  expect(screen.queryByTestId('chart')).toBeNull(); expect(button('确认图表')).toBeDisabled(); expect(screen.queryByText('new insight')).toBeNull();
});
it.each(['规则推荐', 'AI 图表顾问'])('locks preview for the entire %s request', async name => {
  const pending = deferred<typeof recommendation>();
  vi.mocked(recommendChart).mockReturnValue(pending.promise);
  vi.mocked(chartInsight).mockImplementation(async () => ({ recommendation: await pending.promise, insight: '', caveats: [], model: 'test', source: 'ai' }));
  await open(); fireEvent.click(button(name));
  expect(button('生成预览')).toBeDisabled(); expect(button('规则推荐')).toBeDisabled();
  fireEvent.click(button('生成预览')); expect(generateChart).not.toHaveBeenCalled();
  await act(async () => pending.resolve(recommendation)); await screen.findByTestId('chart'); expect(button('确认图表')).not.toBeDisabled();
});
it('discards an old preview when the project changes', async () => {
  const pending = deferred<ReturnType<typeof chart>>(); vi.mocked(generateChart).mockReturnValueOnce(pending.promise);
  const view = await open(); fireEvent.click(button('生成预览'));
  wizard.state = { ...wizard.state, currentProjectId: 'other' }; view.rerender(<VisualizationPage />);
  await act(async () => pending.resolve(chart('old project')));
  expect(screen.queryByTestId('chart')).toBeNull(); expect(button('确认图表')).toBeDisabled();
});
it('does not start generation for a recommendation returned after unmount', async () => {
  const pending = deferred<typeof recommendation>(); vi.mocked(recommendChart).mockReturnValue(pending.promise);
  const view = await open(); fireEvent.click(button('规则推荐')); view.unmount();
  await act(async () => pending.resolve(recommendation)); expect(generateChart).not.toHaveBeenCalled();
});

it('ignores an obsolete dataset load after data replacement', async () => {
  const pending = deferred<Awaited<ReturnType<typeof loadDataset>>>();
  vi.mocked(loadDataset).mockReturnValueOnce(pending.promise);
  const view = render(<VisualizationPage />);
  wizard.state = { ...wizard.state, dataRef: 'b', datasetRevision: 2 };
  view.rerender(<VisualizationPage />);
  await waitFor(() => expect(button('规则推荐')).not.toBeDisabled());
  await act(async () => pending.resolve({ dataset_id: 'obsolete', revision: 1, columns: [], rows: [] } as never));
  fireEvent.click(button('生成预览')); await screen.findByTestId('chart');
  expect(generateChart).toHaveBeenCalledWith(expect.objectContaining({ dataset_id: 'a' }));
});
it('prevents synchronous duplicate recommendation requests', async () => {
  const pending = deferred<typeof recommendation>(); vi.mocked(recommendChart).mockReturnValue(pending.promise);
  await open();
  act(() => { button('规则推荐').click(); button('规则推荐').click(); button('生成预览').click(); });
  expect(recommendChart).toHaveBeenCalledTimes(1); expect(generateChart).not.toHaveBeenCalled();
  await act(async () => pending.resolve(recommendation)); await screen.findByTestId('chart');
});
it('generates count recommendations without a numeric Y column', async () => {
  vi.mocked(recommendChart).mockResolvedValue({ ...recommendation, aggregation: 'count', y_axis: '' });
  await open(); fireEvent.click(button('规则推荐')); await screen.findByTestId('chart');
  expect(generateChart).toHaveBeenCalledWith(expect.objectContaining({ aggregation: 'count', y_axis: '' }));
  expect(button('确认图表')).not.toBeDisabled();
});
it('confirms only the successfully generated replacement', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ blob: async () => new Blob(['png']) })));
  try {
    await open(); fireEvent.click(button('生成预览')); await screen.findByTestId('chart');
    vi.mocked(generateChart).mockResolvedValueOnce(chart('B'));
    fireEvent.click(button('规则推荐')); await waitFor(() => expect(screen.getByTestId('chart')).toHaveTextContent('B'));
    fireEvent.click(button('确认图表'));
    await waitFor(() => expect(wizard.setChart).toHaveBeenCalledWith(expect.objectContaining({ title: { text: 'B' } }), expect.any(Blob)));
    expect(wizard.navigate).toHaveBeenCalledWith('/ppt');
  } finally { vi.unstubAllGlobals(); }
});
