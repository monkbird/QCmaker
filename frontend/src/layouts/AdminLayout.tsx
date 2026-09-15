import {
  AuditOutlined, BankOutlined, BarChartOutlined, BookOutlined, CloudServerOutlined, DatabaseOutlined,
  FilePptOutlined, FileSearchOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, MonitorOutlined,
  SafetyCertificateOutlined, SettingOutlined, TeamOutlined,
} from '@ant-design/icons'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { adminActivity, adminLogout } from '../api/admin'
import { useAdminSession } from './AdminSessionContext'

const navigation = [
  { section: '运营视图', items: [
    { path: '/admin/overview', label: '总览看板', icon: MonitorOutlined },
    { path: '/admin/usage', label: '用量成本', icon: BarChartOutlined },
    { path: '/admin/budget', label: '预算预留', icon: BankOutlined },
  ] },
  { section: '资源管理', items: [
    { path: '/admin/datasets', label: '数据集', icon: DatabaseOutlined },
    { path: '/admin/discussions', label: '研讨会话', icon: TeamOutlined },
    { path: '/admin/files', label: '成果文件', icon: FilePptOutlined },
    { path: '/admin/rag', label: '项目知识库', icon: BookOutlined },
  ] },
  { section: '运维与安全', items: [
    { path: '/admin/logs', label: '运维日志', icon: FileSearchOutlined },
    { path: '/admin/system', label: '系统状态', icon: CloudServerOutlined },
    { path: '/admin/security', label: '安全中心', icon: SafetyCertificateOutlined },
    { path: '/admin/config', label: '管理配置', icon: SettingOutlined },
    { path: '/admin/audit', label: '审计日志', icon: AuditOutlined },
  ] },
]

function remainingLabel(expiresAt?: string) {
  if (!expiresAt) return '会话期限未知'
  const remaining = Math.max(0, new Date(expiresAt).valueOf() - Date.now())
  const minutes = Math.floor(remaining / 60000)
  const hours = Math.floor(minutes / 60)
  return hours > 0 ? `空闲期限 ${hours}小时${minutes % 60}分` : `空闲期限 ${minutes}分钟`
}

export function AdminLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { session, setSession } = useAdminSession()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const lastActivity = useRef(0)
  const active = useMemo(() => navigation.flatMap((group) => group.items).find((item) => location.pathname === item.path)?.path ?? '/admin/overview', [location.pathname])

  useEffect(() => {
    const markActivity = () => {
      const now = Date.now()
      if (now - lastActivity.current < 45000) return
      lastActivity.current = now
      void adminActivity().then(setSession).catch(() => undefined)
    }
    window.addEventListener('pointerdown', markActivity)
    window.addEventListener('keydown', markActivity)
    return () => { window.removeEventListener('pointerdown', markActivity); window.removeEventListener('keydown', markActivity) }
  }, [setSession])

  const logout = () => { void adminLogout().catch(() => undefined).finally(() => navigate('/admin/login', { replace: true })) }
  const currentLabel = navigation.flatMap((group) => group.items).find((item) => item.path === active)?.label ?? '总览看板'

  return <div className="admin-root">
    <div className="admin-ambient" aria-hidden="true"><span className="admin-orb admin-orb--cyan" /><span className="admin-orb admin-orb--violet" /><span className="admin-orbit" /></div>
    <div className={`admin-workspace${collapsed ? ' is-collapsed' : ''}${mobileOpen ? ' is-mobile-open' : ''}`}>
      <aside className="admin-sidebar" aria-label="管理后台主导航">
        <div className="admin-rail"><span className="admin-rail-label">ADMIN CONSOLE</span><button type="button" className="admin-icon-button" aria-label={collapsed ? '展开侧栏' : '收起侧栏'} aria-expanded={!collapsed} onClick={() => setCollapsed((value) => !value)}>{collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}</button></div>
        <div className="admin-identity"><span className="admin-avatar">Q</span><div><small>欢迎回来，</small><strong>{session?.user.username ?? 'Admin'}<em>管理员</em></strong></div></div>
        <div className="admin-search"><FileSearchOutlined /><input aria-label="搜索功能" placeholder="搜索功能…" onChange={(event) => { const target = navigation.flatMap((group) => group.items).find((item) => item.label.includes(event.target.value)); if (target && event.target.value) navigate(target.path) }} /><kbd>⌘ K</kbd></div>
        <nav className="admin-nav">{navigation.map((group) => <div key={group.section} className="admin-nav-group"><p>{group.section}</p>{group.items.map(({ path, label, icon: Icon }) => <button key={path} type="button" className={`admin-nav-item${active === path ? ' is-active' : ''}`} aria-current={active === path ? 'page' : undefined} title={label} onClick={() => { navigate(path); setMobileOpen(false) }}><span className="admin-nav-icon"><Icon /></span><span className="admin-nav-label">{label}</span></button>)}</div>)}</nav>
        <div className="admin-sidebar-bottom"><div className="admin-connection"><span className="admin-status-dot" />管理会话有效<small>当前服务</small></div><button type="button" className="admin-profile" onClick={() => navigate('/admin/security')}><span className="admin-mini-avatar">{session?.user.username.slice(0, 1).toUpperCase() ?? 'A'}</span><span><strong>管理会话</strong><small>{remainingLabel(session?.idle_expires_at)}</small></span><span className="admin-profile-chevron">›</span></button><button type="button" className="admin-logout-button" onClick={logout}><LogoutOutlined />退出管理后台</button></div>
      </aside>
      <main className="admin-main"><header className="admin-topbar"><div className="admin-breadcrumb"><button type="button" className="admin-mobile-menu" aria-label="打开导航" onClick={() => setMobileOpen((value) => !value)}>☰</button><span className="admin-top-mark">Q<span>✦</span></span><span>QCmaker</span><i>/</i><strong>{currentLabel}</strong></div><div className="admin-top-actions"><span className="admin-env-tag"><i />本地管理工作空间</span><button type="button" className="admin-top-avatar" aria-label="打开安全中心" onClick={() => navigate('/admin/security')}>{session?.user.username.slice(0, 1).toUpperCase() ?? 'A'}</button></div></header><div className="admin-content"><Outlet /></div><footer className="admin-footer"><span><i className="admin-status-dot" />管理操作均有记录</span><span>QCmaker Admin · v2</span></footer></main>
    </div>
  </div>
}
