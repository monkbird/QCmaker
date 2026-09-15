import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Outlet, createBrowserRouter, useLocation } from 'react-router'
import { Spin } from 'antd'
import { ErrorBoundary } from '../components/ErrorBoundary'
import { WizardProvider, useWizard } from '../context/WizardContext'
import { routeForState } from '../hooks/useWizardGuard'
import { WizardLayout } from '../layouts/WizardLayout'
import { AdminGuard } from '../layouts/AdminGuard'
import { AdminLayout } from '../layouts/AdminLayout'
import { AdminSessionProvider } from '../layouts/AdminSessionContext'

const ConfigPage = lazy(() => import('../pages/ConfigPage').then((module) => ({ default: module.ConfigPage })))
const TopicPage = lazy(() => import('../pages/TopicPage').then((module) => ({ default: module.TopicPage })))
const DataPage = lazy(() => import('../pages/DataPage').then((module) => ({ default: module.DataPage })))
const DiscussionPage = lazy(() => import('../pages/DiscussionPage').then((module) => ({ default: module.DiscussionPage })))
const VisualizationPage = lazy(() => import('../pages/VisualizationPage').then((module) => ({ default: module.VisualizationPage })))
const PPTPage = lazy(() => import('../pages/PPTPage').then((module) => ({ default: module.PPTPage })))

const AdminLoginPage = lazy(() => import('../pages/admin/AdminLoginPage').then((module) => ({ default: module.AdminLoginPage })))
const OverviewPage = lazy(() => import('../pages/admin/OverviewPage').then((module) => ({ default: module.OverviewPage })))
const UsagePage = lazy(() => import('../pages/admin/UsagePage').then((module) => ({ default: module.UsagePage })))
const BudgetPage = lazy(() => import('../pages/admin/BudgetPage').then((module) => ({ default: module.BudgetPage })))
const DatasetsPage = lazy(() => import('../pages/admin/DatasetsPage').then((module) => ({ default: module.DatasetsPage })))
const DiscussionsPage = lazy(() => import('../pages/admin/DiscussionsPage').then((module) => ({ default: module.DiscussionsPage })))
const FilesPage = lazy(() => import('../pages/admin/FilesPage').then((module) => ({ default: module.FilesPage })))
const RagPage = lazy(() => import('../pages/admin/RagPage').then((module) => ({ default: module.RagPage })))
const LogsPage = lazy(() => import('../pages/admin/LogsPage').then((module) => ({ default: module.LogsPage })))
const SystemPage = lazy(() => import('../pages/admin/SystemPage').then((module) => ({ default: module.SystemPage })))
const SecurityPage = lazy(() => import('../pages/admin/SecurityPage').then((module) => ({ default: module.SecurityPage })))
const AdminConfigPage = lazy(() => import('../pages/admin/ConfigPage').then((module) => ({ default: module.ConfigPage })))
const AuditPage = lazy(() => import('../pages/admin/AuditPage').then((module) => ({ default: module.AuditPage })))

function Page({ children }: { children: ReactNode }) {
  return <Suspense fallback={<div className="admin-state-page"><Spin /><span>正在加载页面</span></div>}>{children}</Suspense>
}

function WizardGuard() {
  const { state } = useWizard()
  const location = useLocation()
  if (state.hydration === 'loading' || state.configStatus === 'checking') return <div className="boot-state"><Spin /><span>正在恢复工作区</span></div>
  const target = routeForState(location.pathname, state)
  return target ? <Navigate to={target} replace /> : <Outlet />
}

function AdminRoot() {
  return <AdminSessionProvider><Outlet /></AdminSessionProvider>
}

function BusinessRoot() {
  return <WizardProvider><ErrorBoundary><WizardLayout /></ErrorBoundary></WizardProvider>
}

export const router = createBrowserRouter([
  {
    path: '/admin',
    element: <AdminRoot />,
    children: [
      { path: 'login', element: <Page><AdminLoginPage /></Page> },
      {
        element: <AdminGuard />,
        children: [{
          element: <AdminLayout />,
          children: [
            { index: true, element: <Navigate to="overview" replace /> },
            { path: 'overview', element: <Page><OverviewPage /></Page> },
            { path: 'usage', element: <Page><UsagePage /></Page> },
            { path: 'budget', element: <Page><BudgetPage /></Page> },
            { path: 'datasets', element: <Page><DatasetsPage /></Page> },
            { path: 'discussions', element: <Page><DiscussionsPage /></Page> },
            { path: 'files', element: <Page><FilesPage /></Page> },
            { path: 'rag', element: <Page><RagPage /></Page> },
            { path: 'logs', element: <Page><LogsPage /></Page> },
            { path: 'system', element: <Page><SystemPage /></Page> },
            { path: 'security', element: <Page><SecurityPage /></Page> },
            { path: 'config', element: <Page><AdminConfigPage /></Page> },
            { path: 'audit', element: <Page><AuditPage /></Page> },
            { path: '*', element: <Navigate to="overview" replace /> },
          ],
        }],
      },
    ],
  },
  {
    element: <BusinessRoot />,
    children: [{
      element: <WizardGuard />,
      children: [
        { path: '/config', element: <Page><ConfigPage /></Page> },
        { path: '/topic', element: <Page><TopicPage /></Page> },
        { path: '/data', element: <Page><DataPage /></Page> },
        { path: '/discussion', element: <Page><DiscussionPage /></Page> },
        { path: '/visualization', element: <Page><VisualizationPage /></Page> },
        { path: '/ppt', element: <Page><PPTPage /></Page> },
      ],
    }, { path: '*', element: <Navigate to="/topic" replace /> }],
  },
])
