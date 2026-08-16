import { AppstoreOutlined, FilePptOutlined, MenuFoldOutlined, PlusOutlined, SettingOutlined } from '@ant-design/icons'
import { Button, Steps } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { IconAction } from '../components/IconAction'
import { useWizard } from '../context/WizardContext'

const steps=[['/config','配置'],['/topic','选题'],['/data','数据'],['/discussion','研讨'],['/visualization','图表'],['/ppt','成果']]
export function WizardLayout(){
  const location=useLocation();const navigate=useNavigate();const{reset}=useWizard();const current=Math.max(0,steps.findIndex(([path])=>path===location.pathname))
  return <div className="app-shell"><header className="topbar"><button className="brand" onClick={()=>navigate('/topic')}><span className="brand-mark"><AppstoreOutlined/></span><span><strong>QCmaker</strong><small>质量课题工作台</small></span></button><div className="step-rail"><Steps size="small" current={current} items={steps.map(([,title])=>({title}))} onChange={(index)=>{const target=steps[index];if(target&&index<=current)navigate(target[0])}}/></div><div className="top-actions"><IconAction label="系统配置" icon={<SettingOutlined/>} onClick={()=>navigate('/config')}/><Button size="middle" icon={<PlusOutlined/>} onClick={()=>void reset().then(()=>navigate('/topic'))}>新课题</Button></div></header><div className="shell-grid"><aside className="side-index"><span>QC</span><i/><b>{String(current+1).padStart(2,'0')}</b><small>/ 06</small><MenuFoldOutlined/></aside><Outlet/></div><div className="ambient-grid" aria-hidden="true"/><div className="version-stamp"><FilePptOutlined/> QC FLOW · LOCAL</div></div>
}
