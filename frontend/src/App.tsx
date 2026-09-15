import { ConfigProvider, App as AntApp, theme } from 'antd'
import { RouterProvider } from 'react-router'
import { ErrorBoundary } from './components/ErrorBoundary'
import { router } from './routes/router'

export default function App() {
  return (
    <ConfigProvider theme={{
      algorithm: theme.darkAlgorithm,
      token: {
        colorPrimary: '#92d9ff',
        colorInfo: '#92d9ff',
        colorText: '#f4f8ff',
        colorTextSecondary: '#c2d7f5',
        colorTextPlaceholder: '#a7bfe2',
        colorBorder: '#364258',
        colorBgContainer: 'rgba(3,8,18,.35)',
        colorBgElevated: '#0e182b',
        borderRadius: 10,
        fontSize: 13,
        fontFamily: '"Segoe UI","Microsoft YaHei",sans-serif',
        controlHeight: 32,
      },
      components: {
        Button: { primaryShadow: '0 3px 10px rgba(24,77,190,.18)', fontWeight: 600 },
        Card: { headerBg: 'transparent', headerHeight: 44, paddingLG: 18 },
        Form: { itemMarginBottom: 16, verticalLabelPadding: '0 0 5px' },
        Table: { headerBg: '#194777', cellPaddingBlock: 10, cellPaddingInline: 12 },
        Modal: { contentBg: '#123269', headerBg: '#123269' },
      },
    }}>
      <AntApp><ErrorBoundary><RouterProvider router={router} /></ErrorBoundary></AntApp>
    </ConfigProvider>
  )
}
