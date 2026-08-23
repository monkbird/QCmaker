import { ApiOutlined, CheckCircleOutlined, CloudServerOutlined, KeyOutlined, LinkOutlined, ReloadOutlined, SaveOutlined, TeamOutlined } from '@ant-design/icons'
import { Alert, AutoComplete, Button, Card, Form, Input, Select, Skeleton, Space, Tag, Tooltip, message } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { checkConnectivity, getConfig, getModels, getProviders, updateConfig } from '../api/config'
import { errorMessage } from '../api/client'
import { StepPage } from '../components/StepPage'
import { useWizard } from '../context/WizardContext'
import type { ConfigUpdate, ConfigView, ModelProvider } from '../types/api'

const regionName:Record<string,string>={cn:'国内服务',global:'国际服务',local:'本地运行',custom:'自定义中转',plan:'Coding 套餐',gateway:'聚合网关'}
const ROLE_SLOTS:[string,string][]=[
  ['moderator','主持人'],['researcher','研究员'],['analyst','数据分析师'],['critic','反方评审'],
  ['writer','成果撰稿人'],['topic','选题评估'],['data','清洗顾问'],['chart','图表顾问'],
]

export function ConfigPage(){
  const[form]=Form.useForm<ConfigUpdate>();const[config,setConfig]=useState<ConfigView|null>(null);const[providers,setProviders]=useState<ModelProvider[]>([]);const[models,setModels]=useState<string[]>([]);const[modelsFetchedAt,setModelsFetchedAt]=useState<Date|null>(null);const[loading,setLoading]=useState(true);const[saving,setSaving]=useState(false);const[modelLoading,setModelLoading]=useState(false)
  const[roleModels,setRoleModels]=useState<Record<string,string>>({});const[roleSaving,setRoleSaving]=useState(false);const[modelsCache,setModelsCache]=useState<Record<string,string[]>>({})
  const[credProvider,setCredProvider]=useState<string|undefined>();const[credKey,setCredKey]=useState('');const[credBaseUrl,setCredBaseUrl]=useState('');const[credSaving,setCredSaving]=useState(false)
  const navigate=useNavigate();const{setConfigStatus}=useWizard();const providerId=Form.useWatch('llm_provider',form)??'openai';const provider=providers.find(item=>item.id===providerId)
  useEffect(()=>{void Promise.all([getConfig(),getProviders()]).then(([c,p])=>{setConfig(c);setProviders(p);setRoleModels(c.role_models??{});const local=c.llm_provider==='ollama';form.setFieldsValue({...c,llm_provider:c.llm_provider,openai_base_url:local?c.local_llm_url:c.openai_base_url,openai_model:local?c.local_llm_model:c.openai_model,openai_api_key:'',tavily_api_key:''})}).catch(e=>message.error(errorMessage(e))).finally(()=>setLoading(false))},[form])
  const providerOptions=useMemo(()=>Object.entries(regionName).map(([region,label])=>({label,options:providers.filter(item=>item.region===region).map(item=>({label:item.name,value:item.id}))})).filter(group=>group.options.length),[providers])
  const credProviderOptions=useMemo(()=>providers.filter(item=>item.region!=='local').map(item=>({label:item.name,value:item.id})),[providers])
  const chooseProvider=(id:string)=>{const next=providers.find(item=>item.id===id);if(!next)return;form.setFieldsValue({llm_provider:id,openai_base_url:next.base_url,openai_model:'',openai_api_key:''});setModels([]);setModelsFetchedAt(null)}
  const loadModels=async()=>{const values=form.getFieldsValue();const selectedProvider=values.llm_provider??'openai';const hasSavedKey=Boolean(config?.has_openai_key&&config.llm_provider===selectedProvider)||Boolean(config?.credential_providers?.includes(selectedProvider));if(selectedProvider!=='ollama'&&!values.openai_api_key&&!hasSavedKey){message.warning('请先填写该服务商的 API Key，再联网获取模型');return}setModelLoading(true);try{const result=await getModels({provider:selectedProvider,base_url:values.openai_base_url,api_key:values.openai_api_key||undefined});setModels(result.models);setModelsCache(current=>({...current,[selectedProvider]:result.models}));setModelsFetchedAt(new Date());message.success(`已从厂商接口获取 ${result.models.length} 个模型`)}catch(e){setModels([]);setModelsFetchedAt(null);message.error(errorMessage(e))}finally{setModelLoading(false)}}
  const save=async(values:ConfigUpdate)=>{setSaving(true);try{const local=values.llm_provider==='ollama';const next=await updateConfig({...values,use_local_llm:local,local_llm_url:local?values.openai_base_url:undefined,local_llm_model:local?values.openai_model:undefined});setConfig(next);setConfigStatus(next.status);message.success('模型服务已保存并立即生效');navigate('/topic')}catch(e){message.error(errorMessage(e))}finally{setSaving(false)}}
  const check=async()=>{try{const values=form.getFieldsValue();const result=await checkConnectivity({provider:values.llm_provider??'openai',base_url:values.openai_base_url,api_key:values.openai_api_key||undefined,model:values.openai_model});message.success(`${result.model} · ${result.latency_ms}ms`)}catch(e){message.error(errorMessage(e))}}
  const setRole=(slot:string,patch:{provider?:string;model?:string})=>{setRoleModels(current=>{const value=current[slot]??'';const[p]=value.split('|');const nextProvider=patch.provider!==undefined?patch.provider:p;const providerChanged=patch.provider!==undefined&&patch.provider!==p;const nextModel=providerChanged?'':patch.model!==undefined?patch.model:value.split('|')[1]??'';const next={...current};if(!nextProvider)delete next[slot];else next[slot]=[nextProvider,nextModel].filter(Boolean).join('|');return next})}
  const saveRoles=async()=>{setRoleSaving(true);try{const next=await updateConfig({role_models:roleModels});setConfig(next);message.success('角色分工已保存')}catch(e){message.error(errorMessage(e))}finally{setRoleSaving(false)}}
  const saveCredential=async()=>{if(!credProvider){message.warning('请选择要保存密钥的服务商');return}if(!credKey.trim()){message.warning('请输入 API Key');return}setCredSaving(true);try{const next=await updateConfig({provider_credentials:{[credProvider]:{api_key:credKey.trim(),base_url:credBaseUrl.trim()||undefined}}});setConfig(next);setCredKey('');setCredBaseUrl('');message.success(`已保存 ${credProvider} 的凭据，可在角色分工中使用`)}catch(e){message.error(errorMessage(e))}finally{setCredSaving(false)}}
  const fetchRoleModels=async(slot:string)=>{const target=roleModels[slot];if(!target)return message.warning('该角色当前跟随主模型');const pid=target.split('|')[0];try{const cached=modelsCache[pid];const list=cached??(await getModels({provider:pid})).models;if(!cached)setModelsCache(current=>({...current,[pid]:list}));setRoleModels(current=>{const value=current[slot]??'';const model=value.split('|')[1]??'';return{...current,[slot]:list.includes(model)||!model?`${pid}|${model||(list[0]??'')}`:`${pid}|${model}`}});message.success(`${pid} 共 ${list.length} 个模型，点击模型输入框即可下拉选择`)}catch(e){message.error(errorMessage(e))}}
  return <StepPage eyebrow="01 · SYSTEM" title="模型与协同" description="主模型负责兜底；Coding 套餐与聚合网关按角色分配，形成多视角协作。" aside={config&&<Tag color={config.status==='ready'?'success':'warning'}>{config.status==='ready'?'服务就绪':'等待配置'}</Tag>} actions={<><Button icon={<ApiOutlined/>} onClick={()=>void check()}>测试连接</Button><Button type="primary" icon={<SaveOutlined/>} loading={saving} onClick={()=>form.submit()}>保存并继续</Button></>}>
    {loading?<Skeleton active/>:<div className="config-grid">
      <div className="config-top">
      <Card className="panel-card provider-card" title={<span><CloudServerOutlined/> 主模型服务</span>} extra={<Tag>未分配角色的默认</Tag>}><Form form={form} layout="vertical" onFinish={save} requiredMark={false}>
        <Form.Item name="llm_provider" label="主模型服务商" rules={[{required:true}]}><Select showSearch optionFilterProp="label" options={providerOptions} onChange={chooseProvider}/></Form.Item>
        <div className="provider-meta"><span className={`region-mark region-mark--${provider?.region??'custom'}`}>{provider?regionName[provider.region]:'自定义'}</span><span>{provider?.api_style==='ollama'?'本地模型仓库':'OpenAI 兼容接口'}</span>{provider?.key_url&&<a href={provider.key_url} target="_blank" rel="noreferrer"><LinkOutlined/> 获取密钥</a>}{provider?.docs_url&&<a href={provider.docs_url} target="_blank" rel="noreferrer">接口文档</a>}</div>
        <Form.Item name="openai_base_url" label="API 地址" rules={[{required:true,message:'请输入厂商 API 地址'}]}><Input placeholder="https://…/v1"/></Form.Item>
        {providerId!=='ollama'&&<Form.Item name="openai_api_key" label="API Key / 套餐令牌" rules={[{required:!(config?.has_openai_key&&config.llm_provider===providerId)&&!config?.credential_providers?.includes(providerId),message:'切换服务商时请输入对应的 API Key'}]} extra={config?.credential_providers?.includes(providerId)?'凭据库已存此服务商的 Key，可直接留空':config?.has_openai_key&&config.llm_provider===providerId?'已配置；留空表示不修改':'密钥仅保存在本机，不回显'}><Input.Password placeholder={config?.has_openai_key&&config.llm_provider===providerId?'已配置（不显示）':'粘贴 API Key 或 Coding Plan 令牌'}/></Form.Item>}
        <Form.Item name="openai_model" label={<span>模型名称 <small className="field-hint">点击输入框获取厂商模型</small></span>} rules={[{required:true,message:'请选择或输入模型名称'}]}><AutoComplete options={models.map(value=>({value,label:value}))} filterOption={(input,option)=>String(option?.value??'').toLowerCase().includes(input.toLowerCase())} onFocus={()=>{if(!modelLoading)void loadModels()}}><Input suffix={<Tooltip title="刷新厂商模型"><Button type="text" size="small" className="model-refresh" loading={modelLoading} icon={<ReloadOutlined/>} onClick={event=>{event.preventDefault();event.stopPropagation();void loadModels()}} aria-label="刷新厂商模型"/></Tooltip>} placeholder="选择或手工输入模型 ID"/></AutoComplete></Form.Item>
        {modelsFetchedAt&&<div className="model-source"><i className="is-live"/>厂商实时清单 · {modelsFetchedAt.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})} 获取</div>}
        <Form.Item name="tavily_api_key" label="Tavily Key（可选）" extra={config?.has_tavily_key?'已配置；留空表示不修改':'用于研究员联网检索'}><Input.Password/></Form.Item>
      </Form></Card>
      <Card className="panel-card cred-card" title={<span><KeyOutlined/> 服务商凭据库</span>} extra={<Space size={4} wrap>{config?.credential_providers?.length?config.credential_providers.map(pid=><Tag key={pid} color="green">{pid}</Tag>):<Tag>暂无</Tag>}</Space>}>
        <p style={{color:'var(--muted)',fontSize:12,margin:'0 0 10px'}}>为主模型之外的服务商保存 Key；保存后即可在下方「角色分工」中把它们指派给任意角色。Coding Plan 请粘贴套餐控制台提供的 Key。</p>
        <div className="cred-form">
          <Select showSearch optionFilterProp="label" placeholder="选择服务商（套餐 / 网关 / 厂商）" value={credProvider} options={credProviderOptions} onChange={id=>{setCredProvider(id);const preset=providers.find(item=>item.id===id)?.base_url;setCredBaseUrl(preset&&preset.startsWith('https://')?'':credBaseUrl)}}/>
          <Input.Password placeholder="API Key / 计划令牌" value={credKey} onChange={e=>setCredKey(e.target.value)}/>
          <Input placeholder="自定义 API 地址（可选，留空用官方默认）" value={credBaseUrl} onChange={e=>setCredBaseUrl(e.target.value)}/>
          <Button type="primary" block loading={credSaving} onClick={()=>void saveCredential()}>保存凭据</Button>
        </div>
        <div className="security-note" style={{marginTop:12}}><CheckCircleOutlined/> 密钥只存本机 · 不回显 · 覆盖保存即换钥</div>
      </Card>
      </div>
      <Card className="panel-card roles-card" title={<span><TeamOutlined/> 角色分工（多模型协同）</span>} extra={<Button size="small" type="primary" loading={roleSaving} onClick={()=>void saveRoles()}>保存分工</Button>}>
        <Alert style={{marginBottom:14}} type="info" showIcon message="未分配的角色跟随主模型；给反方评审、图表顾问指定不同厂商的模型，即可形成真正的多视角研讨。"/>
        <div className="role-grid">{ROLE_SLOTS.map(([slot,label])=>{const value=roleModels[slot]??'';const[rid,model]=value.split('|');return <div key={slot} className="role-row">
          <span className="role-name">{label}</span>
          <Select allowClear showSearch optionFilterProp="label" size="small" placeholder="跟随主模型" value={rid||undefined} options={providers.map(item=>({label:item.name,value:item.id}))} onChange={(id)=>setRole(slot,{provider:id??'',model:''})}/>
          <AutoComplete size="small" value={model||''} options={(modelsCache[rid]??[]).map(v=>({value:v,label:v}))} filterOption={(input,option)=>String(option?.value??'').toLowerCase().includes(input.toLowerCase())} onChange={v=>setRole(slot,{model:v})}><Input size="small" placeholder={modelsCache[rid]?.length?'搜索或选择模型':'模型 ID（↻ 拉取清单）'}/></AutoComplete>
          <Tooltip title="校验该厂商模型清单可用性（需已保存其凭据）"><Button size="small" icon={<ReloadOutlined/>} onClick={()=>void fetchRoleModels(slot)}/></Tooltip>
        </div>})}</div>
        <div className="security-note" style={{marginTop:14}}><CheckCircleOutlined/> 额度按各套餐/厂商口径分别消耗 · 预算账本在后台持续记录</div>
      </Card>
    </div>}
  </StepPage>
}
