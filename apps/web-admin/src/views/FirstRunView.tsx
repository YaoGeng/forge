import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Space, Spin, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fetchFirstRunStats, type FirstRunStat } from '../api'
import { GATE_TEXT, gateVerdict } from '../gate'
import { useApi } from '../useApi'

const columns: ColumnsType<FirstRunStat> = [
  {
    title: '应用',
    dataIndex: 'app',
    render: (name: string) => <Typography.Text code>{name}</Typography.Text>,
  },
  { title: '首跑数', dataIndex: 'first_runs' },
  { title: '成功', dataIndex: 'ok_first_runs' },
  {
    title: '首跑成功率',
    dataIndex: 'rate',
    render: (rate: number) => `${(rate * 100).toFixed(1)}%`,
  },
  {
    title: '判定',
    render: (_: unknown, row: FirstRunStat) => {
      const v = gateVerdict({ first_runs: row.first_runs, rate: row.rate })
      return (
        <Space size={4}>
          {v.met ? (
            <Tag color="green">达标</Tag>
          ) : (
            <Tag color="red">未达标</Tag>
          )}
          {!v.met && v.reason && (
            <Typography.Text type="secondary">{v.reason}</Typography.Text>
          )}
        </Space>
      )
    },
  },
]

/** 视图①：首跑统计（D-5' 面板）——判定文案与 backend web_admin.py GATE_TEXT 一字不差 */
export default function FirstRunView() {
  const { state, reload } = useApi(fetchFirstRunStats)

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert type="info" showIcon message={GATE_TEXT} />
      {state.phase === 'error' && (
        <Alert
          type="error"
          showIcon
          message="首跑统计加载失败"
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
        <Table<FirstRunStat>
          rowKey="app"
          columns={columns}
          dataSource={state.data}
          locale={{ emptyText: '暂无首跑数据——公开开放后此处按应用聚合。' }}
        />
      )}
    </Space>
  )
}
