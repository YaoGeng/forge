import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Space, Spin, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useState } from 'react'
import { fetchAppVersions, fetchApps, type AppSummary, type AppVersionRow } from '../api'
import { useApi } from '../useApi'

/** 单应用版本列表的懒加载状态（行展开时才拉 E1，按 app 缓存） */
type VersionState =
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'done'; data: AppVersionRow[] }

const appColumns: ColumnsType<AppSummary> = [
  { title: 'ID', dataIndex: 'id', width: 64 },
  {
    title: '应用名',
    dataIndex: 'name',
    render: (name: string) => <Typography.Text code>{name}</Typography.Text>,
  },
  { title: '标题', dataIndex: 'title', render: (t: string) => t || '—' },
  { title: '最新版本', dataIndex: 'version', render: (v: string | null) => v || '—' },
  {
    title: '状态',
    dataIndex: 'status',
    render: (s: string | null) => (s ? <Tag>{s}</Tag> : '—'),
  },
]

const versionColumns: ColumnsType<AppVersionRow> = [
  { title: 'ID', dataIndex: 'id', width: 64 },
  {
    title: '版本号',
    dataIndex: 'version',
    render: (v: string) => <Typography.Text code>{v}</Typography.Text>,
  },
  { title: '状态', dataIndex: 'status', render: (s: string) => <Tag>{s}</Tag> },
  { title: '创建时间', dataIndex: 'created_at' },
]

function errMsg(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

/** 视图②：应用与版本——GET /api/v1/apps 列表，行展开拉 GET /api/v1/apps/{id}/versions（E1） */
export default function AppsView() {
  const { state, reload } = useApi(fetchApps)
  const [versions, setVersions] = useState<Record<number, VersionState>>({})

  const loadVersions = useCallback((appId: number) => {
    setVersions((prev) => ({ ...prev, [appId]: { phase: 'loading' } }))
    fetchAppVersions(appId).then(
      (data) => setVersions((prev) => ({ ...prev, [appId]: { phase: 'done', data } })),
      (err: unknown) =>
        setVersions((prev) => ({
          ...prev,
          [appId]: { phase: 'error', message: errMsg(err) },
        })),
    )
  }, [])

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {state.phase === 'error' && (
        <Alert
          type="error"
          showIcon
          message="应用列表加载失败"
          description={state.message}
          action={
            <Button size="small" danger icon={<ReloadOutlined />} onClick={reload}>
              重试
            </Button>
          }
        />
      )}
      {state.phase === 'loading' && (
        <div style={{ padding: 48, textAlign: 'center' }}>
          <Spin size="large" />
        </div>
      )}
      {state.phase === 'done' && (
        <Table<AppSummary>
          rowKey="id"
          columns={appColumns}
          dataSource={state.data}
          locale={{ emptyText: '暂无应用——创作者注册应用后此处展示。' }}
          expandable={{
            onExpand: (expanded, record) => {
              if (expanded && !versions[record.id]) {
                loadVersions(record.id)
              }
            },
            expandedRowRender: (record) => {
              const vs = versions[record.id]
              if (!vs || vs.phase === 'loading') {
                return (
                  <div style={{ padding: 24, textAlign: 'center' }}>
                    <Spin />
                  </div>
                )
              }
              if (vs.phase === 'error') {
                return (
                  <Alert
                    type="error"
                    showIcon
                    message={`版本列表加载失败（${record.name}）`}
                    description={vs.message}
                    action={
                      <Button
                        size="small"
                        danger
                        icon={<ReloadOutlined />}
                        onClick={() => loadVersions(record.id)}
                      >
                        重试
                      </Button>
                    }
                  />
                )
              }
              return (
                <Table<AppVersionRow>
                  rowKey="id"
                  columns={versionColumns}
                  dataSource={vs.data}
                  size="small"
                  pagination={false}
                  locale={{ emptyText: '暂无版本' }}
                />
              )
            },
          }}
        />
      )}
    </Space>
  )
}
