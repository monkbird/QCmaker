import { render, screen } from '@testing-library/react';
import { it, expect, vi } from 'vitest';
import { ChapterContentPreview } from '../components/authoring/ChapterContentPreview';

vi.mock('echarts-for-react/lib/core', () => ({ default: () => <div data-testid="chapter-chart" /> }));

it('renders structured table and chart blocks with origin marker', () => {
  render(<ChapterContentPreview blocks={[
    { kind: 'table', title: '产量表', columns: ['区域', '产量'], rows: [{ 区域: '甲', 产量: 12 }] },
    { kind: 'chart', title: '趋势', chart_type: 'line', unit: '公斤/亩', rows: [{ label: '前', value: 10 }], origin_kind: 'simulation' } as never,
  ]} />);
  expect(screen.getByText('产量表')).toBeInTheDocument();
  expect(screen.getByText('甲')).toBeInTheDocument();
  expect(screen.getByText('【模拟】趋势')).toBeInTheDocument();
  expect(screen.getByTestId('chapter-chart')).toBeInTheDocument();
});
