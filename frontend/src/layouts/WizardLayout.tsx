import {
  AppstoreOutlined, BarChartOutlined, CommentOutlined,
  DatabaseOutlined, FilePptOutlined, PlusOutlined, SettingOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { Alert, Button, Select, message } from 'antd'
import { useEffect, useState } from 'react'
import { listSavedProjects } from '../storage/db'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { IconAction } from '../components/IconAction'
import { useWizard } from '../context/WizardContext'

const steps = [
  { path: '/topic', title: '确定课题', icon: ThunderboltOutlined },
  { path: '/authoring', title: '逐章编写', icon: CommentOutlined },
  { path: '/ppt', title: '成果检查', icon: FilePptOutlined },
]
const tools = [
  { path: '/data', title: '资料与数据', icon: DatabaseOutlined },
  { path: '/visualization', title: '图表工具', icon: BarChartOutlined },
  { path: '/discussion', title: '数据研讨', icon: CommentOutlined },
  { path: '/config', title: '模型配置', icon: SettingOutlined },
]

export function WizardLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { reset, notice, state, openProject } = useWizard()
  const [projects, setProjects] = useState<{value:string;label:string}[]>([])
  useEffect(() => { void listSavedProjects().then(items => setProjects(items.map(p => ({value:p.projectId,label:p.snapshot?.topic ?? '未命名课题'})))).catch(() => undefined) }, [state.currentProjectId, state.topic])
  const current = steps.findIndex(step => step.path === location.pathname)
  const currentTitle = [...steps, ...tools].find(item => item.path === location.pathname)?.title ?? '课题工作区'

  return (
    <div className="app-shell">
      <header className="topbar">
        <button type="button" className="brand" onClick={() => navigate('/topic')} aria-label="QCmaker 质量课题工作台">
          <span className="brand-mark"><AppstoreOutlined /></span>
          <span><strong>QCmaker</strong><small>质量课题工作台</small></span>
        </button>
        <div className="workspace-context"><span>课题工作区</span><i aria-hidden="true">/</i><strong>{currentTitle}</strong></div>
        <div className="top-actions">
          <Select aria-label="恢复历史课题" placeholder="历史课题" style={{width:180}} value={projects.some(p=>p.value===state.currentProjectId)?state.currentProjectId:undefined} options={projects} onChange={id=>void openProject(id).then(()=>navigate('/authoring')).catch(()=>message.error('恢复课题失败'))}/>
          <IconAction label="系统配置" icon={<SettingOutlined />} onClick={() => navigate('/config')} />
          <Button size="middle" icon={<PlusOutlined />} onClick={() => void reset().then(() => navigate('/topic')).catch(() => message.error('创建课题失败，请检查浏览器存储'))}>新课题</Button>
        </div>
      </header>
      {state.legacyArtifactsStale && <Alert type="warning" showIcon message="课题名称已修改，已有资料和成果已保留；旧流程成果需复核标题和适用范围。" />}{notice && <Alert type="warning" showIcon message={notice} />}
      <div className="shell-grid">
        <aside className="side-index">
          <span className="nav-caption">创作流程</span>
          <nav className="step-nav" aria-label="课题步骤">
            {steps.map(({ path, title, icon: Icon }, index) => (
              <button
                type="button"
                key={path}
                className={`step-link${index === current ? ' is-active' : ''}`}
                aria-current={index === current ? 'step' : undefined}

                onClick={() => navigate(path)}
              >
                <span className="step-link-icon"><Icon /></span>
                <span className="step-link-label">{title}</span>
                <span className="step-link-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
              </button>
            ))}
          </nav>
          <span className="nav-caption" style={{marginTop:20}}>辅助工具</span>
          <nav className="step-nav" aria-label="辅助工具">
            {tools.map(({path,title,icon:Icon})=><button key={path} type="button" className={`step-link${location.pathname===path?' is-active':''}`} aria-current={location.pathname===path?'page':undefined} onClick={()=>navigate(path)}><span className="step-link-icon"><Icon/></span><span className="step-link-label">{title}</span></button>)}
          </nav>
          <div className="side-progress">
            <FilePptOutlined />
            <strong>从课题到成果</strong>
            <small>按章节推进，资料随时补充</small>
          </div>
        </aside>
        <Outlet />
      </div>
      <div className="ambient-grid" aria-hidden="true" />
      <div className="version-stamp">QCMAKER · WORKSPACE</div>
    </div>
  )
}
