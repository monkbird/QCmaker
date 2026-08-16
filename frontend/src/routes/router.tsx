import { Suspense, lazy } from 'react'
import { Navigate, Outlet, createBrowserRouter, useLocation } from 'react-router'
import { Spin } from 'antd'
import { WizardLayout } from '../layouts/WizardLayout'
import { useWizard } from '../context/WizardContext'
import { routeForState } from '../hooks/useWizardGuard'
const ConfigPage=lazy(()=>import('../pages/ConfigPage').then(module=>({default:module.ConfigPage})))
const TopicPage=lazy(()=>import('../pages/TopicPage').then(module=>({default:module.TopicPage})))
const DataPage=lazy(()=>import('../pages/DataPage').then(module=>({default:module.DataPage})))
const DiscussionPage=lazy(()=>import('../pages/DiscussionPage').then(module=>({default:module.DiscussionPage})))
const VisualizationPage=lazy(()=>import('../pages/VisualizationPage').then(module=>({default:module.VisualizationPage})))
const PPTPage=lazy(()=>import('../pages/PPTPage').then(module=>({default:module.PPTPage})))
function Page({children}:{children:React.ReactNode}){return <Suspense fallback={<div className="boot-state"><Spin/><span>正在加载步骤</span></div>}>{children}</Suspense>}
function Guard(){const{state}=useWizard();const location=useLocation();if(state.hydration==='loading'||state.configStatus==='checking')return <div className="boot-state"><Spin/><span>正在恢复工作区</span></div>;const target=routeForState(location.pathname,state);return target?<Navigate to={target} replace/>:<Outlet/>}
export const router=createBrowserRouter([{element:<WizardLayout/>,children:[{element:<Guard/>,children:[{path:'/config',element:<Page><ConfigPage/></Page>},{path:'/topic',element:<Page><TopicPage/></Page>},{path:'/data',element:<Page><DataPage/></Page>},{path:'/discussion',element:<Page><DiscussionPage/></Page>},{path:'/visualization',element:<Page><VisualizationPage/></Page>},{path:'/ppt',element:<Page><PPTPage/></Page>}]},{path:'*',element:<Navigate to="/topic" replace/>}]}])
