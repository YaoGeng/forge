import {
  AppstoreOutlined,
  AuditOutlined,
  DashboardOutlined,
} from '@ant-design/icons'
import { Layout, Menu, Spin, Typography } from 'antd'
import { lazy, Suspense, useState } from 'react'

// 三视图按需分包（无路由库，MUST NOT 卡面钉死：antd Menu + 本地 state 切页）
const FirstRunView = lazy(() => import('./views/FirstRunView'))
const AppsView = lazy(() => import('./views/AppsView'))
const RunReportsView = lazy(() => import('./views/RunReportsView'))

type ViewKey = 'first-run' | 'apps' | 'run-reports'

const menuItems = [
  { key: 'first-run', icon: <DashboardOutlined />, label: '首跑统计' },
  { key: 'apps', icon: <AppstoreOutlined />, label: '应用与版本' },
  { key: 'run-reports', icon: <AuditOutlined />, label: '认证记录' },
]

export default function App() {
  const [view, setView] = useState<ViewKey>('first-run')

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider theme="light" width={208} breakpoint="lg" collapsedWidth={0}>
        <div style={{ padding: '20px 16px 8px' }}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            Forge 管理域
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            web-admin · 只读面板
          </Typography.Text>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[view]}
          onClick={(e) => setView(e.key as ViewKey)}
          items={menuItems}
        />
      </Layout.Sider>
      <Layout.Content style={{ padding: 24 }}>
        <Suspense
          fallback={
            <div style={{ padding: 48, textAlign: 'center' }}>
              <Spin size="large" />
            </div>
          }
        >
          {view === 'first-run' && <FirstRunView />}
          {view === 'apps' && <AppsView />}
          {view === 'run-reports' && <RunReportsView />}
        </Suspense>
      </Layout.Content>
    </Layout>
  )
}
