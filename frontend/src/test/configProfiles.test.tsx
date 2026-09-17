import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router';

vi.mock('../context/WizardContext', () => ({ useWizard: () => ({ setConfigStatus: vi.fn() }) }));
vi.mock('../components/StepPage', () => ({ StepPage: ({ children, actions }: { children: ReactNode; actions: ReactNode }) => <>{children}{actions}</> }));
vi.mock('../api/config', () => ({
  getProviders: vi.fn().mockResolvedValue([{ id: 'openai', name: 'OpenAI', region: 'global', base_url: 'https://api.example/v1', api_style: 'openai' }]),
  getProfiles: vi.fn().mockResolvedValue({ config_revision: 4, active_profile_id: 'p1', profiles: [{ profile_id: 'p1', config_revision: 4, active: true, credential_configured: {}, draft: { name: '现场方案', default_model: { service_id: 'svc', model: 'm1' }, roles: { writer: { service_id: 'svc', model: 'm2' } }, services: [{ service_id: 'svc', provider: 'openai', base_url: 'https://api.example/v1' }], search: null } }] }),
  activateProfile: vi.fn(), saveProfile: vi.fn(), probeDraft: vi.fn(), getModels: vi.fn(), testSearch: vi.fn(),
}));
import { ConfigPage } from '../pages/ConfigPage';
import { getModels, getProfiles, probeDraft, saveProfile } from '../api/config';

describe('configuration profile interaction', () => {
  it('identifies the incomplete role and blocks both save and probe before sending invalid payloads', async () => {
    const result = structuredClone(await getProfiles());
    result.profiles[0].draft.roles.writer = { service_id: 'svc', model: '' };
    vi.mocked(getProfiles).mockResolvedValueOnce(result);
    vi.mocked(saveProfile).mockClear();
    vi.mocked(probeDraft).mockClear();
    render(<MemoryRouter><ConfigPage /></MemoryRouter>);
    await screen.findByDisplayValue('现场方案');
    fireEvent.click(screen.getByRole('button', { name: /测试连接/ }));
    fireEvent.click(screen.getByRole('button', { name: /保存并继续/ }));
    expect(screen.getAllByText(/成果撰稿人：请选择模型，或将服务改为“跟随默认”/).length).toBeGreaterThan(0);
    expect(saveProfile).not.toHaveBeenCalled();
    expect(probeDraft).not.toHaveBeenCalled();
  });
  it('shows fetched models even when the old selected model belongs to another provider', async () => {
    vi.mocked(getModels).mockResolvedValueOnce({ models: ['deepseek-chat', 'deepseek-reasoner'], source: 'remote' });
    render(<MemoryRouter><ConfigPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '获取模型' }));
    await screen.findByText(/已获取 2 个模型/);
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '默认模型' }));
    fireEvent.focus(screen.getByRole('combobox', { name: '默认模型' }));
    fireEvent.click(await screen.findByTitle('deepseek-chat'));
    fireEvent.click(screen.getByRole('button', { name: '保存配置' }));
    await waitFor(() => expect(saveProfile).toHaveBeenCalledWith(expect.objectContaining({ draft: expect.objectContaining({ default_model: { service_id: 'svc', model: 'deepseek-chat' } }) })));
  });
  it('shows pending and persistent failure feedback when fetching models', async () => {
    let reject!: (reason: unknown) => void;
    vi.mocked(getModels).mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
    render(<MemoryRouter><ConfigPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '获取模型' }));
    expect(await screen.findByText('正在获取模型…')).toBeInTheDocument();
    reject({ message: '接口地址无法连接' });
    expect(await screen.findByText(/获取失败：接口地址无法连接/)).toBeInTheDocument();
  });
  it('reports an empty model list', async () => {
    vi.mocked(getModels).mockResolvedValueOnce({ models: [], source: 'remote' });
    render(<MemoryRouter><ConfigPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '获取模型' }));
    expect(await screen.findByText(/未返回可选模型/)).toBeInTheDocument();
  });
  it('removes a service and clears its default and role bindings before saving', async () => {
    render(<MemoryRouter><ConfigPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '删除服务 OpenAI' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认删除' }));
    expect(screen.queryByText('m2')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '保存配置' }));
    await waitFor(() => expect(saveProfile).toHaveBeenCalledWith(expect.objectContaining({ draft: expect.objectContaining({ services: [], default_model: null, roles: { writer: null } }) })));
  });
  it('renders and hydrates the active saved profile', async () => {
    render(<MemoryRouter><ConfigPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByDisplayValue('现场方案')).toBeInTheDocument());
    expect(screen.queryByText('svc')).not.toBeInTheDocument();
    expect(screen.getByText('m2')).toBeInTheDocument();
  });
});
