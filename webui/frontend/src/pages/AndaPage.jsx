import { useState, useEffect } from 'react'
import { Row, Col, Card, Tag, Skeleton, Alert, Steps, Descriptions, Table, Empty } from 'antd'
import {
  DeploymentUnitOutlined,
  CheckCircleOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import { getAndaActiveDeployment } from '../services/api'

// The Network Change Agent runs approved SOPs as DeploymentPlans in anda-system.
// This page shows the plan running now and the most recent ones, as recorded on
// the DeploymentPlan resources (the same data `kubectl get deploymentplans` shows).

const PHASE_COLOR = {
  Pending: 'orange',
  InProgress: 'blue',
  Completed: 'green',
  Failed: 'red',
  PartiallyFailed: 'red',
  RolledBack: 'purple',
  Cancelled: 'default',
}

const formatTime = (iso) => (iso ? new Date(iso).toLocaleTimeString() : '—')

const ActivePlan = ({ deployment, loading }) => {
  if (loading) return <Skeleton active paragraph={{ rows: 4 }} />
  if (deployment?.error) {
    return <Alert type="warning" showIcon message="DeploymentPlans could not be read" description={deployment.error} />
  }
  if (!deployment?.active) {
    return (
      <div style={{ textAlign: 'center', padding: '24px 0' }}>
        <CheckCircleOutlined style={{ fontSize: 40, color: '#52c41a', display: 'block', marginBottom: 12 }} />
        <div style={{ fontSize: 16, fontWeight: 600, color: '#52c41a' }}>No change running</div>
        <div style={{ fontSize: 13, color: '#8c8c8c', marginTop: 4 }}>
          A change starts when you approve a proposal in Decisions
        </div>
      </div>
    )
  }

  const stages = deployment.stages || []
  const current = stages.findIndex(s => s.status === 'active')
  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16, borderRadius: 6 }}
        message={
          <span style={{ fontWeight: 600 }}>
            Running: <Tag color="blue">{deployment.nf}</Tag>
            <Tag color={PHASE_COLOR[deployment.stage] || 'default'}>{deployment.stage}</Tag>
          </span>
        }
        description={deployment.reasoning}
      />
      {stages.length > 0 && (
        <Steps
          size="small"
          current={current >= 0 ? current : 0}
          style={{ marginBottom: 16 }}
          items={stages.map(s => ({
            title: s.name,
            status: s.status === 'done' ? 'finish' : s.status === 'active' ? 'process' : 'wait',
          }))}
        />
      )}
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="DeploymentPlan">{deployment.plan_name}</Descriptions.Item>
        <Descriptions.Item label="Alarm">{deployment.alarm || '—'}</Descriptions.Item>
        <Descriptions.Item label="SOP">{deployment.sop || '—'}</Descriptions.Item>
        <Descriptions.Item label="Steps so far">{deployment.steps ?? '—'}</Descriptions.Item>
      </Descriptions>
    </div>
  )
}

const HISTORY_COLUMNS = [
  { title: 'Started', dataIndex: 'created', width: 100, render: formatTime },
  { title: 'Alarm', dataIndex: 'alarm', render: a => a || '—' },
  { title: 'NF', dataIndex: 'nf', width: 70, render: nf => <Tag>{(nf || '').toUpperCase()}</Tag> },
  { title: 'SOP', dataIndex: 'sop', ellipsis: true },
  { title: 'Result', dataIndex: 'phase', width: 120, render: p => <Tag color={PHASE_COLOR[p] || 'default'}>{p}</Tag> },
  {
    title: 'Duration',
    dataIndex: 'elapsed_seconds',
    width: 100,
    render: (s, row) => (s != null ? `${s}s${row.steps ? ` · ${row.steps} steps` : ''}` : '—'),
  },
]

const AndaPage = () => {
  const [deployment, setDeployment] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = () => {
      getAndaActiveDeployment()
        .then(data => setDeployment(data))
        .catch(() => setDeployment({ active: false, history: [], error: 'Request failed' }))
        .finally(() => setLoading(false))
    }
    load()
    const interval = deployment?.active ? 5000 : 15000
    const t = setInterval(load, interval)
    return () => clearInterval(t)
  }, [deployment?.active])

  const history = deployment?.history || []

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={10}>
        <Card
          title={<span><DeploymentUnitOutlined style={{ marginRight: 8, color: '#1890FF' }} />Change running now</span>}
          bordered={false}
          style={{ borderRadius: 8 }}
        >
          <ActivePlan deployment={deployment} loading={loading} />
        </Card>
      </Col>
      <Col xs={24} lg={14}>
        <Card
          title={<span><HistoryOutlined style={{ marginRight: 8, color: '#722ed1' }} />Recent changes</span>}
          bordered={false}
          style={{ borderRadius: 8 }}
        >
          {loading ? (
            <Skeleton active paragraph={{ rows: 3 }} />
          ) : history.length === 0 ? (
            <Empty description="No changes yet. Each approved proposal appears here as a DeploymentPlan." />
          ) : (
            <Table
              size="small"
              rowKey="name"
              pagination={false}
              columns={HISTORY_COLUMNS}
              dataSource={history}
              expandable={{
                expandedRowRender: row => (
                  <Descriptions size="small" column={1}>
                    <Descriptions.Item label="DeploymentPlan">{row.name}</Descriptions.Item>
                    <Descriptions.Item label="Reason">{row.reason || '—'}</Descriptions.Item>
                    <Descriptions.Item label="Message">{row.message || '—'}</Descriptions.Item>
                    <Descriptions.Item label="Finished">{formatTime(row.finished)}</Descriptions.Item>
                  </Descriptions>
                ),
              }}
            />
          )}
        </Card>
      </Col>
    </Row>
  )
}

export default AndaPage
