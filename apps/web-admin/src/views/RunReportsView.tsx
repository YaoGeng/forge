import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Space, Spin, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchRunReports, type RunReportRow } from '../api'
import { useApi } from '../useApi'

const columns: ColumnsType<RunReportRow> = [
  { title: '#', dataIndex: 'id', width: 72 },
  {
    title: '应用',
    dataIndex: 'app_name',
    render: (name: string) => <Typography.Text code>{name}</Typography.Text>,
  },
  {
    title: '结果',
    dataIndex: 'ok',
    width: 96,
    render: (ok: boolean) =>
      ok ? <Tag color="green">✓ 成功</Tag> : <Tag color="red">✗ 失败</Tag>,
  },
  {
    title: '失败类',
    dataIndex: 'failure_class',
    render: (fc: string | null) => fc || '—',
  },
  { title: '环境', dataIndex: 'env_class' },
  {
    title: '首跑',
    dataIndex: 'first_run',
    width: 80,
    render: (fr: boolean) => (fr ? <Tag color="blue">首跑</Tag> : '—'),
  },
  { title: '时间', dataIndex: 'created_at' },
]

/** 视图③：认证记录——GET /api/v1/stats/run-reports?limit=50（E3，id desc 最新 50 条） */
// loader 必须模块级稳定引用（useApi 以其身份做 effect 依赖）
const loadRunReports = () => fetchRunReports(50)

export default function RunReportsView() {
  const { state, reload } = useApi(loadRunReports)

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {state.phase === 'error' && (
        <Alert
          type="error"
          showIcon
          message="认证记录加载失败"
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
        <Table<RunReportRow>
          rowKey="id"
          columns={columns}
          dataSource={state.data}
          locale={{ emptyText: '暂无上报记录——买家侧运行上报后此处展示最新 50 条。' }}
        />
      )}
    </Space>
  )
}
