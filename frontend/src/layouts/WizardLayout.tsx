import {
  AppstoreOutlined, BarChartOutlined, CheckOutlined, CommentOutlined,
  DatabaseOutlined, FilePptOutlined, PlusOutlined, SettingOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { Alert, Button, message } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { IconAction } from '../components/IconAction'
import { useWizard } from '../context/WizardContext'

const steps = [
  { path: '/config', title: '配置', icon: SettingOutlined },
  { path: '/topic', title: '选题', icon: ThunderboltOutlined },
  { path: '/data', title: '数据', icon: DatabaseOutlined },
  { path: '/discussion', title: '研讨', icon: CommentOutlined },
  { path: '/visualization', title: '图表', icon: BarChartOutlined },
  { path: '/ppt', title: '成果', icon: FilePptOutlined },
]

export function WizardLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { reset, notice } = useWizard()
  const current = Math.max(0, steps.findIndex(step => step.path === location.pathname))

  return (
    <div className="app-shell">
      <header className="topbar">
        <button type="button" className="brand" onClick={() => navigate('/topic')} aria-label="QCmaker 质量课题工作台">
          <span className="brand-mark"><AppstoreOutlined /></span>
          <span><strong>QCmaker</strong><small>质量课题工作台</small></span>
        </button>
        <div className="workspace-context"><span>课题工作区</span><i aria-hidden="true">/</i><strong>{steps[current].title}</strong></div>
        <div className="top-actions">
          <IconAction label="系统配置" icon={<SettingOutlined />} onClick={() => navigate('/config')} />
          <Button size="middle" icon={<PlusOutlined />} onClick={() => void reset().then(() => navigate('/topic')).catch(() => message.error('创建课题失败，请检查浏览器存储'))}>新课题</Button>
        </div>
      </header>
      {notice && <Alert type="warning" showIcon message={notice} />}
      <div className="shell-grid">
        <aside className="side-index">
          <span className="nav-caption">创作流程</span>
          <nav className="step-nav" aria-label="课题步骤">
            {steps.map(({ path, title, icon: Icon }, index) => (
              <button
                type="button"
                key={path}
                className={`step-link${index === current ? ' is-active' : ''}${index < current ? ' is-complete' : ''}`}
                aria-current={index === current ? 'step' : undefined}
                disabled={index > current}
                onClick={() => navigate(path)}
              >
                <span className="step-link-icon"><Icon /></span>
                <span className="step-link-label">{title}</span>
                <span className="step-link-number" aria-hidden="true">{index < current ? <CheckOutlined /> : String(index + 1).padStart(2, '0')}</span>
              </button>
            ))}
          </nav>
          <div className="side-progress">
            <FilePptOutlined />
            <strong>从课题到成果</strong>
            <small>当前步骤 {current + 1} / {steps.length}</small>
            <div className="side-progress-track" aria-hidden="true"><span style={{ width: `${((current + 1) / steps.length) * 100}%` }} /></div>
          </div>
        </aside>
        <Outlet />
      </div>
      <div className="ambient-grid" aria-hidden="true" />
      <div className="version-stamp">QCMAKER · WORKSPACE</div>
    </div>
  )
}
