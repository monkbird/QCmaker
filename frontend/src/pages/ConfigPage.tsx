import { ApiOutlined, DeleteOutlined, PlusOutlined, SaveOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Input, Modal, Select, Skeleton, Space, Tag, message } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { activateProfile, getModels, getProfiles, getProviders, probeDraft, saveProfile, testSearch, type ProbeReport } from '../api/config';
import { errorMessage } from '../api/client';
import { StepPage } from '../components/StepPage';
import { useWizard } from '../context/WizardContext';
import type { ModelProvider } from '../types/api';
import type { ConfigDraft, ConfigProfile, ServiceDraft } from '../api/config';
import './ConfigPage.css';
import { ModelPicker } from '../components/ModelPicker';

const ROLES = [['moderator','主持人'],['researcher','研究员'],['analyst','数据分析师'],['critic','反方评审'],['writer','成果撰稿人'],['topic','选题评估'],['data','清洗顾问'],['chart','图表顾问']] as const;
const emptyDraft = (): ConfigDraft => ({ name: '当前配置', default_model: null, roles: {}, services: [], search: null });
const hydrate = (d: ConfigDraft): ConfigDraft => ({ ...d, roles: { ...d.roles }, services: d.services.map(s => ({ ...s, api_key: undefined })), search: d.search ? { ...d.search, api_key: undefined } : null });

export function ConfigPage() {
  const [providers, setProviders] = useState<ModelProvider[]>([]); const [profiles, setProfiles] = useState<ConfigProfile[]>([]);
  const [draft, setDraft] = useState<ConfigDraft>(emptyDraft); const [selected, setSelected] = useState<string>(); const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true); const [saving, setSaving] = useState(false); const [dirty, setDirty] = useState(false); const [pending, setPending] = useState<string>(); const [probe, setProbe] = useState<ProbeReport | null>(null); const [searchStatus, setSearchStatus] = useState<string>(); const [models, setModels] = useState<Record<string,string[]>>({}); const probeVersion = useRef(0); const searchVersion = useRef(0);
  const [modelStatus, setModelStatus] = useState<Record<string, { state: 'loading' | 'success' | 'error'; text: string }>>({});
  const [deleteId, setDeleteId] = useState<string>();
  const modelRequests = useRef<Record<string, number>>({});
  const navigate = useNavigate(); const { setConfigStatus } = useWizard(); const providerMap = useMemo(() => new Map(providers.map(p => [p.id, p])), [providers]);
  useEffect(() => { void Promise.all([getProviders(), getProfiles()]).then(([ps, result]) => { setProviders(ps); setProfiles(result.profiles); setSelected(result.active_profile_id ?? undefined); setRevision(result.config_revision); const p = result.profiles.find(x => x.profile_id === result.active_profile_id); if (p) setDraft(hydrate(p.draft as ConfigDraft)); }).catch(e => message.error(errorMessage(e))).finally(() => setLoading(false)); }, []);
  const mark = (next: ConfigDraft) => { setDraft(next); setDirty(true); setProbe(null); };
  const clearModels = (id: string) => {
    modelRequests.current[id] = (modelRequests.current[id] ?? 0) + 1;
    setModels(m => ({ ...m, [id]: [] }));
    setModelStatus(m => { const next = { ...m }; delete next[id]; return next; });
  };
  const updateService = (i: number, patch: Partial<ServiceDraft>) => {
    const service = draft.services[i];
    clearModels(service.service_id);
    const changedProvider = patch.provider !== undefined && patch.provider !== service.provider;
    const resetBinding = (binding: ConfigDraft['default_model']) => changedProvider && binding?.service_id === service.service_id ? { ...binding, model: '' } : binding;
    mark({ ...draft, services: draft.services.map((s, n) => n === i ? { ...s, ...patch } : s),
      default_model: resetBinding(draft.default_model),
      roles: Object.fromEntries(Object.entries(draft.roles).map(([role, binding]) => [role, resetBinding(binding)])) });
  };
  const activate = async (id: string) => { try { const r = await activateProfile(id, revision); setSelected(id); setRevision(r.config_revision); draft.services.forEach(s => clearModels(s.service_id)); setDraft(hydrate(r.draft as ConfigDraft)); setSearchStatus(undefined); setDirty(false); setProbe(null); setProfiles(ps => ps.map(p => ({ ...p, active: p.profile_id === id }))); } catch (e) { message.error(errorMessage(e)); } };
  const switchTo = (id: string) => { if (dirty) setPending(id); else void activate(id); };
  const draftIssues = [
    ...(!draft.name.trim() ? ['请填写方案名称'] : []),
    ...(draft.default_model && !draft.default_model.model.trim() ? ['默认模型：请选择或输入模型 ID'] : []),
    ...ROLES.flatMap(([role, label]) => draft.roles[role] && !draft.roles[role]!.model.trim()
      ? [`${label}：请选择模型，或将服务改为“跟随默认”`] : []),
    ...draft.services.flatMap((service, index) => !service.base_url.trim() ? [`服务 ${index + 1}：请填写接口地址`] : []),
  ];
  const validateDraft = () => {
    if (!draftIssues.length) return true;
    message.error(draftIssues[0]);
    return false;
  };
  const save = async (asNew = false, continueToTopic = false): Promise<boolean> => { if (!validateDraft()) return false; setSaving(true); try { const outgoing = asNew ? { ...draft, name: `方案 ${new Date().toLocaleString('zh-CN')}` } : draft; const r = await saveProfile({ profile_id: asNew ? undefined : selected, expected_revision: revision, draft: outgoing }); setSelected(r.profile_id); setRevision(r.config_revision); setDraft(hydrate(r.draft as ConfigDraft)); setDirty(false); setProfiles(ps => [r, ...ps.filter(p => p.profile_id !== r.profile_id)]); setConfigStatus('ready'); message.success('配置方案已保存并立即生效'); if (continueToTopic) navigate('/topic'); return true; } catch (e) { message.error(errorMessage(e)); return false; } finally { setSaving(false); } };
  const test = async () => { if (!validateDraft()) return; const v = ++probeVersion.current; try { const r = await probeDraft({ draft_version: v, expected_revision: revision, draft }); if (v === probeVersion.current) setProbe(r); } catch (e) { message.error(errorMessage(e)); } };
  const searchTest = async () => { if (!validateDraft()) return; const v = ++searchVersion.current; try { const r = await testSearch({ draft_version: v, expected_revision: revision, draft }); if (v === searchVersion.current) setSearchStatus(`${r.status}: ${r.message}`); } catch (e) { message.error(errorMessage(e)); } };
  const fetchModels = async (service: ServiceDraft) => {
    const id = service.service_id;
    const request = (modelRequests.current[id] ?? 0) + 1;
    modelRequests.current[id] = request;
    setModelStatus(m => ({ ...m, [id]: { state: 'loading', text: '正在获取模型…' } }));
    try {
      const r = await getModels({ provider: service.provider, base_url: service.base_url, api_key: service.api_key, credential_id: service.credential_id });
      if (modelRequests.current[id] !== request) return;
      setModels(m => ({ ...m, [id]: r.models }));
      setModelStatus(m => ({ ...m, [id]: r.models.length
        ? { state: 'success', text: `已获取 ${r.models.length} 个模型，可在默认模型和角色模型中搜索选择。` }
        : { state: 'error', text: '服务未返回可选模型，请检查接口地址，或手动输入模型 ID。' } }));
    } catch (e) {
      if (modelRequests.current[id] !== request) return;
      setModelStatus(m => ({ ...m, [id]: { state: 'error', text: `获取失败：${errorMessage(e)}。可重试，或手动输入模型 ID。` } }));
    }
  };
  const removeService = () => {
    if (!deleteId) return;
    clearModels(deleteId);
    mark({ ...draft, services: draft.services.filter(s => s.service_id !== deleteId),
      default_model: draft.default_model?.service_id === deleteId ? null : draft.default_model,
      roles: Object.fromEntries(Object.entries(draft.roles).map(([role, binding]) => [role, binding?.service_id === deleteId ? null : binding])) });
    setDeleteId(undefined);
  };
  const addService = () => {
    let index = 1;
    while (draft.services.some(s => s.service_id === `service-${index}`)) index++;
    mark({ ...draft, services: [...draft.services, { service_id: `service-${index}`, provider: providers[0]?.id ?? 'openai', base_url: providers[0]?.base_url ?? '' }] });
  };
  const serviceLabel = (service: ServiceDraft) => {
    const name = providerMap.get(service.provider)?.name ?? service.provider;
    const peers = draft.services.filter(s => s.provider === service.provider);
    return peers.length > 1 ? `${name}（${peers.findIndex(s => s.service_id === service.service_id) + 1}）` : name;
  };
  const serviceOptions = draft.services.map(s => ({ value: s.service_id, label: serviceLabel(s) }));
  const modelOptions = (id?: string) => (id ? models[id] ?? [] : []);
  if (loading) return <StepPage eyebrow="01 · SYSTEM" title="模型与协同" description="配置方案"><Skeleton active /></StepPage>;
  return <StepPage eyebrow="01 · SYSTEM" title="模型与协同" description="按角色保存模型服务方案，切换后完整恢复草稿。" actions={<Space><Button icon={<ApiOutlined />} onClick={() => void test()}>测试连接</Button><Button type="primary" loading={saving} icon={<SaveOutlined />} onClick={() => void save(false, true)}>保存并继续</Button></Space>}>
    <div className="config-workspace">
      {draftIssues.length > 0 && <Alert showIcon type="warning" title="请补全以下配置后再测试或保存" description={draftIssues.map(issue => <div key={issue}>{issue}</div>)} />}
      <Card title="配置方案" extra={<Tag color={dirty ? 'gold' : 'green'}>{dirty ? '未保存' : '已保存'}</Tag>}>
        <div className="config-profile-row">
          <label className="config-field"><span>切换方案</span><Select aria-label="切换方案" value={selected} placeholder="选择已保存方案" options={profiles.map(p => ({ value: p.profile_id, label: `${p.draft.name ?? p.profile_id}${p.active ? '（当前）' : ''}` }))} onChange={switchTo} /></label>
          <label className="config-field"><span>方案名称</span><Input value={draft.name} onChange={e => mark({ ...draft, name: e.target.value })} /></label>
          <Space><Button loading={saving} onClick={() => void save()}>保存配置</Button><Button onClick={() => void save(true)}>另存为</Button></Space>
        </div>
        <p className="config-hint">密钥保存在当前部署的服务端，页面不回显。修改后保存即可生效。</p>
      </Card>
      <Card title="服务与默认模型" extra={<Button icon={<PlusOutlined />} onClick={addService}>添加服务</Button>}>
        <div className="config-services">
          {!draft.services.length && <Alert type="info" showIcon message="暂无模型服务，点击“添加服务”开始配置。" />}
          {draft.services.map((s, i) => <section className="config-service" key={s.service_id} aria-label={`服务 ${serviceLabel(s)}`}>
            <div className="config-service-heading"><strong>{serviceLabel(s)}</strong><Button danger type="text" icon={<DeleteOutlined />} aria-label={`删除服务 ${serviceLabel(s)}`} onClick={() => setDeleteId(s.service_id)}>删除服务</Button></div>
            <div className="config-service-fields">
              <label className="config-field"><span>服务商</span><Select aria-label={`服务商 ${serviceLabel(s)}`} value={s.provider} options={providers.map(p => ({ value: p.id, label: p.name }))} onChange={provider => updateService(i, { provider, credential_id: null, api_key: undefined, base_url: providerMap.get(provider)?.base_url ?? '' })} /></label>
              <label className="config-field"><span>接口地址</span><Input value={s.base_url} onChange={e => updateService(i, { base_url: e.target.value, credential_id: null })} /></label>
              <label className="config-field"><span>API Key</span><Input.Password value={s.api_key ?? ''} placeholder={s.credential_id ? '已保存密钥，留空沿用' : '请输入 API Key'} onChange={e => updateService(i, { api_key: e.target.value || undefined })} /></label>
              <Button loading={modelStatus[s.service_id]?.state === 'loading'} onClick={() => void fetchModels(s)}>获取模型</Button>
            </div>
            {modelStatus[s.service_id] && <Alert showIcon type={modelStatus[s.service_id].state === 'error' ? 'error' : modelStatus[s.service_id].state === 'success' ? 'success' : 'info'} message={modelStatus[s.service_id].text} />}
          </section>)}
        </div>
        <div className="config-default">
          <label className="config-field"><span>默认服务</span><Select aria-label="默认服务" allowClear placeholder="选择默认服务" value={draft.default_model?.service_id} options={serviceOptions} onChange={id => mark({ ...draft, default_model: id ? { service_id: id, model: '' } : null })} /></label>
          <label className="config-field"><span>默认模型</span><ModelPicker label="默认模型" disabled={!draft.default_model} value={draft.default_model?.model ?? ''} models={modelOptions(draft.default_model?.service_id)} placeholder="获取模型后选择，或手动输入模型 ID" onChange={model => draft.default_model && mark({ ...draft, default_model: { ...draft.default_model, model } })} /></label>
        </div>
      </Card>
      <div className="config-lower">
        <Card title="角色分工" extra={<span className="config-hint">未单独指定时跟随默认模型</span>}>
          <div className="config-role-grid">{ROLES.map(([role, label]) => { const b = draft.roles[role]; return <div key={role} className="config-role"><strong>{label}</strong><div className="config-role-fields">
            <Select aria-label={`${label}服务`} allowClear placeholder="跟随默认" value={b?.service_id} options={serviceOptions} onChange={id => mark({ ...draft, roles: { ...draft.roles, [role]: id ? { service_id: id, model: draft.default_model?.service_id === id ? draft.default_model.model : b?.service_id === id ? b.model : '' } : null } })} />
            <ModelPicker label={`${label}模型`} disabled={!b} value={b?.model ?? ''} placeholder={b ? '选择或输入模型 ID' : '跟随默认模型'} models={modelOptions(b?.service_id)} onChange={model => b && mark({ ...draft, roles: { ...draft.roles, [role]: { ...b, model } } })} />
          </div>{b && !b.model.trim() && <p className="config-hint" style={{ color: '#ffc069' }}>请选择模型，或清除服务选择以跟随默认。</p>}</div>; })}</div>
        </Card>
        <Card title="联网检索（可选）"><div className="config-search">
          <div><Tag color="blue">Tavily</Tag><p className="config-hint">用于检索公开资料和补充选题依据，独立于模型服务配置。</p></div>
          <label className="config-field"><span>搜索 API Key</span><Input.Password value={draft.search?.api_key ?? ''} placeholder={draft.search?.credential_id ? '已保存密钥，留空沿用' : '请输入 Tavily API Key'} onChange={e => mark({ ...draft, search: { provider: 'tavily', ...(draft.search ?? {}), api_key: e.target.value || undefined } })} /></label>
          <Space wrap><Button onClick={() => void searchTest()}>测试搜索</Button><a href="https://app.tavily.com" target="_blank" rel="noreferrer">获取 Tavily Key ↗</a></Space>
          {searchStatus && <Alert type={searchStatus.startsWith('success') ? 'success' : 'warning'} message={searchStatus} />}
        </div></Card>
      </div>
      {probe && <Alert type={probe.passed ? 'success' : 'warning'} message={probe.passed ? '当前草稿验证通过' : '当前草稿存在未通过项'} description={probe.rows.map(r => `${r.role}: ${r.status} ${r.message}`).join('；')} />}
    </div>
    <Modal open={Boolean(deleteId)} title="删除模型服务" okText="确认删除" cancelText="取消" okButtonProps={{ danger: true }} onOk={removeService} onCancel={() => setDeleteId(undefined)}>删除 {serviceOptions.find(s => s.value === deleteId)?.label} 后，关联的默认模型和角色设置将一并清空。保存配置后生效。</Modal>
    <Modal open={Boolean(pending)} title="当前有未保存变更" onCancel={() => setPending(undefined)} footer={[<Button key="cancel" onClick={() => setPending(undefined)}>取消</Button>, <Button key="discard" onClick={() => { const id = pending; setPending(undefined); setDirty(false); if (id) void activate(id); }}>放弃变更后切换</Button>, <Button key="save" type="primary" onClick={async () => { const ok = await save(); const id = pending; if (ok && id) { setPending(undefined); void activate(id); } }}>保存后切换</Button>]}>切换方案前请处理当前草稿。</Modal>
  </StepPage>;
}
