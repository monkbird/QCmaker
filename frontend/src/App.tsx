import { ConfigProvider, App as AntApp } from 'antd'
import { RouterProvider } from 'react-router'
import { ErrorBoundary } from './components/ErrorBoundary'
import { WizardProvider } from './context/WizardContext'
import { router } from './routes/router'
export default function App(){return <ConfigProvider theme={{token:{colorPrimary:'#087f72',colorInfo:'#087f72',borderRadius:8,fontFamily:'"Noto Sans SC","Microsoft YaHei",sans-serif',controlHeight:32},components:{Button:{primaryShadow:'none',fontWeight:600},Card:{headerBg:'#f7faf9'}}}}><AntApp><ErrorBoundary><WizardProvider><RouterProvider router={router}/></WizardProvider></ErrorBoundary></AntApp></ConfigProvider>}
