import { useState, useEffect } from 'react'
import {
  Row, Col, Card, Tag, Skeleton, Empty, Table, Steps, Badge,
  Progress, Timeline, Spin, Typography,
} from 'antd'
import {
  CloudServerOutlined, CheckCircleOutlined, ClockCircleOutlined,
  ExclamationCircleOutlined, HddOutlined, PlusCircleOutlined,
  ThunderboltOutlined, LoadingOutlined, SyncOutlined,
  ApiOutlined, ClusterOutlined,
} from '@ant-design/icons'
import { getInventory, getInventoryHealth, getProvisioningRequests } from '../services/api'

const { Text } = Typography

// Maps directly to ProvisioningRequest CRD status.phase enum
const PHASE_ORDER = ['Pending', 'Validating', 'Provisioning', 'WaitingForNodes', 'Ready']
const PHASE_META = {
  Pending:         { color: '#FA8C16', icon: <ClockCircleOutlined />,        label: 'Pending',           desc: 'Queued for processing' },
  Validating:      { color: '#1890FF', icon: <ApiOutlined />,                label: 'Validating',        desc: 'Preflight: HW inventory + BMC reachability' },
  Provisioning:    { color: '#722ed1', icon: <ThunderboltOutlined />,         label: 'Provisioning',      desc: 'Tinkerbell OS install in progress' },
  WaitingForNodes: { color: '#13c2c2', icon: <SyncOutlined spin />,           label: 'Waiting for Nodes', desc: 'OS installed — waiting for EKS node registration' },
  Ready:           { color: '#52c41a', icon: <CheckCircleOutlined />,         label: 'Ready',             desc: 'Node registered and healthy in EKS' },
  Failed:          { color: '#ff4d4f', icon: <ExclamationCircleOutlined />,   label: 'Failed',            desc: 'Provisioning failed after retries' },
}

const INVENTORY_PHASE_COLORS = {
  Available: '#52c41a',
  Discovered: '#1890FF',
  Provisioning: '#722ed1',
  Provisioned: '#13c2c2',
  Error: '#ff4d4f',
  Maintenance: '#FA8C16',
}

// ── Active Provisioning Pipeline ──
// Shows the state machine steps for the most recent active request
const ProvisioningPipeline = ({ requests }) => {
  const activeRequests = requests.filter(r => r.phase && r.phase !== 'Ready' && r.phase !== 'Failed')
  const completedRequests = requests.filter(r => r.phase === 'Ready')
  const failedRequests = requests.filter(r => r.phase === 'Failed')

  if (requests.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 0', color: '#8c8c8c' }}>
        <CloudServerOutlined style={{ fontSize: 36, marginBottom: 12, opacity: 0.3 }} />
        <div>No provisioning activity</div>
        <div style={{ fontSize: 12 }}>Create a ProvisioningRequest CR to begin</div>
      </div>
    )
  }

  // Use the first active request to drive the pipeline, or last completed/failed
  const primaryRequest = activeRequests[0] || failedRequests[0] || completedRequests[0]
  if (!primaryRequest) return null

  const currentPhase = primaryRequest.phase || 'Pending'
  const currentIdx = PHASE_ORDER.indexOf(currentPhase)
  const isFailed = currentPhase === 'Failed'

  return (
    <div>
      {/* Request header */}
      <div style={{ marginBottom: 16, padding: '8px 12px', background: '#FAFAFA', borderRadius: 6 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Text strong style={{ fontSize: 13 }}>{primaryRequest.name}</Text>
            <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>{primaryRequest.namespace}</Text>
          </div>
          {activeRequests.length > 0 && (
            <Tag color="processing" icon={<SyncOutlined spin />}>ACTIVE</Tag>
          )}
          {isFailed && <Tag color="error">FAILED</Tag>}
          {currentPhase === 'Ready' && <Tag color="success">COMPLETE</Tag>}
        </div>
        {primaryRequest.nodes && (
          <div style={{ marginTop: 4, fontSize: 11, color: '#8c8c8c' }}>
            {primaryRequest.nodes} node(s) • {primaryRequest.cluster || '—'}
          </div>
        )}
      </div>

      {/* State machine steps */}
      <Steps
        direction="vertical"
        size="small"
        current={isFailed ? currentIdx : (currentIdx >= 0 ? currentIdx : 0)}
        status={isFailed ? 'error' : 'process'}
        items={PHASE_ORDER.map((phase, i) => {
          const meta = PHASE_META[phase]
          let status = 'wait'
          if (isFailed && i <= currentIdx) status = i === currentIdx ? 'error' : 'finish'
          else if (i < currentIdx) status = 'finish'
          else if (i === currentIdx) status = 'process'

          return {
            title: (
              <span style={{ fontSize: 13 }}>
                {meta.label}
                {status === 'process' && !isFailed && (
                  <LoadingOutlined style={{ marginLeft: 8, fontSize: 11, color: meta.color }} />
                )}
              </span>
            ),
            description: <span style={{ fontSize: 11, color: '#8c8c8c' }}>{meta.desc}</span>,
            icon: i <= currentIdx ? meta.icon : undefined,
            status,
          }
        })}
      />

      {/* Summary counters */}
      {requests.length > 1 && (
        <div style={{ marginTop: 12, fontSize: 11, color: '#8c8c8c', borderTop: '1px solid #f0f0f0', paddingTop: 8 }}>
          {activeRequests.length > 0 && <span style={{ marginRight: 12 }}>🔄 {activeRequests.length} active</span>}
          {completedRequests.length > 0 && <span style={{ marginRight: 12 }}>✅ {completedRequests.length} completed</span>}
          {failedRequests.length > 0 && <span>❌ {failedRequests.length} failed</span>}
        </div>
      )}
    </div>
  )
}

// ── Provisioning Requests Table ──
const ProvisioningRequestsTable = ({ requests, loading }) => {
  const columns = [
    {
      title: 'Request',
      dataIndex: 'name',
      key: 'name',
      render: (name, record) => (
        <div>
          <code style={{ fontSize: 12, background: '#f5f5f5', padding: '1px 6px', borderRadius: 3 }}>{name}</code>
          <div style={{ fontSize: 11, color: '#8c8c8c' }}>{record.namespace}</div>
        </div>
      ),
    },
    {
      title: 'Site / Cluster',
      key: 'cluster',
      render: (_, record) => (
        <div>
          <div style={{ fontSize: 12 }}>{record.cluster || record.site || '—'}</div>
          {record.nodes && <div style={{ fontSize: 11, color: '#8c8c8c' }}>{record.nodes} node(s)</div>}
        </div>
      ),
    },
    {
      title: 'Phase',
      dataIndex: 'phase',
      key: 'phase',
      render: phase => {
        const meta = PHASE_META[phase] || { color: '#8c8c8c', icon: null }
        const isActive = phase && phase !== 'Ready' && phase !== 'Failed'
        return (
          <Tag
            icon={isActive ? <SyncOutlined spin /> : meta.icon}
            style={{ color: meta.color, border: `1px solid ${meta.color}`, background: `${meta.color}10` }}
          >
            {phase || 'unknown'}
          </Tag>
        )
      },
    },
    {
      title: 'Message',
      dataIndex: 'message',
      key: 'message',
      ellipsis: true,
      render: msg => msg
        ? <span style={{ fontSize: 11, color: '#595959' }}>{msg}</span>
        : <span style={{ color: '#ccc' }}>—</span>,
    },
    {
      title: 'Updated',
      dataIndex: 'lastUpdated',
      key: 'lastUpdated',
      width: 110,
      render: ts => ts
        ? <span style={{ fontSize: 11, color: '#8c8c8c' }}>
            {new Date(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
          </span>
        : <span style={{ color: '#ccc' }}>—</span>,
    },
  ]

  if (loading) return <Skeleton active paragraph={{ rows: 3 }} />
  if (!requests || requests.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No provisioning requests" />
  }

  return (
    <Table
      dataSource={requests}
      columns={columns}
      rowKey={(r, i) => r.name || i}
      size="small"
      pagination={{ pageSize: 8, hideOnSinglePage: true }}
    />
  )
}

// ── Hardware Inventory Table ──
const HardwareInventoryTable = ({ servers, loading }) => {
  const columns = [
    {
      title: 'Server',
      dataIndex: 'hostname',
      key: 'hostname',
      render: (hostname, record) => (
        <div>
          <strong>{hostname || record.name}</strong>
          {record.bmcAddress && (
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>
              BMC: {record.bmcAddress.replace('http://', '').replace('https://', '')}
            </div>
          )}
        </div>
      ),
    },
    {
      title: 'Hardware',
      key: 'hw',
      render: (_, record) => (
        <div style={{ fontSize: 12 }}>
          {record.cpu_count > 0 && <span>{record.cpu_count} cores</span>}
          {record.memory_gib > 0 && <span style={{ marginLeft: 8 }}>{record.memory_gib} GiB</span>}
          {!record.cpu_count && !record.memory_gib && <span style={{ color: '#ccc' }}>—</span>}
        </div>
      ),
    },
    {
      title: 'Phase',
      dataIndex: 'phase',
      key: 'phase',
      render: phase => {
        const color = INVENTORY_PHASE_COLORS[phase] || '#8c8c8c'
        return (
          <Tag style={{ color, border: `1px solid ${color}`, background: `${color}15` }}>
            {phase || 'unknown'}
          </Tag>
        )
      },
    },
    {
      title: 'Last Seen',
      dataIndex: 'lastDiscovered',
      key: 'lastDiscovered',
      width: 110,
      render: ts => ts
        ? <span style={{ fontSize: 11, color: '#8c8c8c' }}>
            {new Date(ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
          </span>
        : <span style={{ color: '#ccc' }}>—</span>,
    },
  ]

  if (loading) return <Skeleton active paragraph={{ rows: 4 }} />
  if (!servers || servers.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No hardware inventory" />
  }

  return (
    <Table
      dataSource={servers}
      columns={columns}
      rowKey={(r, i) => r.name || r.hostname || i}
      size="small"
      pagination={{ pageSize: 10, hideOnSinglePage: true }}
    />
  )
}

// ── Main Page ──
const AnpaPage = () => {
  const [servers, setServers] = useState([])
  const [inventoryLoading, setInventoryLoading] = useState(true)
  const [healthData, setHealthData] = useState(null)
  const [healthLoading, setHealthLoading] = useState(true)
  const [requests, setRequests] = useState([])
  const [requestsLoading, setRequestsLoading] = useState(true)

  const loadData = () => {
    getInventory()
      .then(data => { setServers(data?.servers || []); setInventoryLoading(false) })
      .catch(() => setInventoryLoading(false))
    getInventoryHealth()
      .then(data => { setHealthData(data); setHealthLoading(false) })
      .catch(() => setHealthLoading(false))
    getProvisioningRequests()
      .then(data => { setRequests(data?.requests || []); setRequestsLoading(false) })
      .catch(() => setRequestsLoading(false))
  }

  useEffect(() => {
    loadData()
    const t = setInterval(loadData, 10000) // 10s poll for responsive state transitions
    return () => clearInterval(t)
  }, [])

  const byPhase = healthData?.by_phase || {}
  const totalServers = healthData?.total || servers.length
  const activeRequests = requests.filter(r =>
    r.phase && r.phase !== 'Ready' && r.phase !== 'Failed'
  )

  return (
    <div>
      {/* KPIs */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card bordered={false} size="small" style={{ textAlign: 'center', background: '#F0F5FF', borderRadius: 8 }}>
            <HddOutlined style={{ fontSize: 20, color: '#1890FF', marginBottom: 4 }} />
            <div style={{ fontSize: 24, fontWeight: 700, color: '#1890FF' }}>{totalServers}</div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>Servers Discovered</div>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card bordered={false} size="small" style={{ textAlign: 'center', background: '#F6FFED', borderRadius: 8 }}>
            <CheckCircleOutlined style={{ fontSize: 20, color: '#52c41a', marginBottom: 4 }} />
            <div style={{ fontSize: 24, fontWeight: 700, color: '#52c41a' }}>{byPhase.Provisioned || byPhase.Ready || 0}</div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>Provisioned</div>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card bordered={false} size="small" style={{ textAlign: 'center', background: activeRequests.length > 0 ? '#F0F5FF' : '#F5F5F5', borderRadius: 8 }}>
            {activeRequests.length > 0
              ? <SyncOutlined spin style={{ fontSize: 20, color: '#1890FF', marginBottom: 4 }} />
              : <ClockCircleOutlined style={{ fontSize: 20, color: '#8c8c8c', marginBottom: 4 }} />
            }
            <div style={{ fontSize: 24, fontWeight: 700, color: activeRequests.length > 0 ? '#1890FF' : '#8c8c8c' }}>
              {activeRequests.length}
            </div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>Active Requests</div>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card bordered={false} size="small" style={{ textAlign: 'center', background: '#F5F5F5', borderRadius: 8 }}>
            <ClusterOutlined style={{ fontSize: 20, color: '#595959', marginBottom: 4 }} />
            <div style={{ fontSize: 24, fontWeight: 700, color: '#595959' }}>{requests.length}</div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>Total Requests</div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        {/* Provisioning Pipeline — driven by real CR state */}
        <Col xs={24} lg={10}>
          <Card
            title={<span><ThunderboltOutlined style={{ marginRight: 8, color: '#722ed1' }} />Provisioning Pipeline</span>}
            bordered={false}
            style={{ borderRadius: 8 }}
            extra={activeRequests.length > 0 && <Badge status="processing" text="Live" />}
          >
            <ProvisioningPipeline requests={requests} />
          </Card>
        </Col>

        {/* Inventory by Phase */}
        <Col xs={24} lg={14}>
          <Card
            title={<span><HddOutlined style={{ marginRight: 8, color: '#595959' }} />Hardware Inventory</span>}
            bordered={false}
            style={{ borderRadius: 8 }}
            extra={<span style={{ fontSize: 11, color: '#8c8c8c' }}>{totalServers} server(s)</span>}
          >
            <HardwareInventoryTable servers={servers} loading={inventoryLoading} />
          </Card>
        </Col>

        {/* Provisioning Requests Table */}
        <Col xs={24}>
          <Card
            title={
              <span>
                <PlusCircleOutlined style={{ marginRight: 8, color: '#1890FF' }} />
                Provisioning Requests
                {activeRequests.length > 0 && (
                  <Badge count={activeRequests.length} size="small" style={{ marginLeft: 8 }} />
                )}
              </span>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
          >
            <ProvisioningRequestsTable requests={requests} loading={requestsLoading} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default AnpaPage
