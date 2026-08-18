import { useState, useEffect } from 'react'
import {
  Row, Col, Card, Tag, Skeleton, Empty, Alert, Button,
  Badge, Tooltip, Divider, Space, message, Modal,
} from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExclamationCircleOutlined,
  ClockCircleOutlined,
  RobotOutlined,
  BulbOutlined,
  WarningOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons'
import { getApprovals, postApprove } from '../services/api'

const SECTION_STYLES = {
  reasoning: {
    bg: '#F3E5F5',
    border: '#CE93D8',
    label: 'AI Reasoning',
    icon: <RobotOutlined />,
    labelColor: '#6A1B9A',
  },
  evidence: {
    bg: '#E8F5E9',
    border: '#A5D6A7',
    label: 'Evidence',
    icon: <BulbOutlined />,
    labelColor: '#2E7D32',
  },
  consequences: {
    bg: '#FFF3E0',
    border: '#FFCC80',
    label: 'Consequences',
    icon: <WarningOutlined />,
    labelColor: '#E65100',
  },
}

const SectionBlock = ({ type, content }) => {
  const cfg = SECTION_STYLES[type]
  if (!content || !cfg) return null

  return (
    <div
      style={{
        background: cfg.bg,
        border: `1px solid ${cfg.border}`,
        borderRadius: 6,
        padding: '10px 12px',
        marginBottom: 10,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: cfg.labelColor,
          textTransform: 'uppercase',
          letterSpacing: 0.8,
          marginBottom: 6,
          display: 'flex',
          alignItems: 'center',
          gap: 5,
        }}
      >
        {cfg.icon}
        {cfg.label}
      </div>
      <div style={{ fontSize: 13, color: '#333', lineHeight: 1.6 }}>
        {Array.isArray(content) ? (
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {content.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        ) : (
          content
        )}
      </div>
    </div>
  )
}

const ApprovalCard = ({ approval, onDecision }) => {
  const [deciding, setDeciding] = useState(false)

  const isPending = !approval.status || approval.status === 'pending'
  const isApproved = approval.status === 'approved'
  const isRejected = approval.status === 'rejected' || approval.status === 'denied'

  const borderColor = isPending ? '#FA8C16'
    : isApproved ? '#52c41a'
    : isRejected ? '#ff4d4f'
    : '#d9d9d9'

  const handleApprove = async () => {
    setDeciding(true)
    try {
      await postApprove(approval.alarm_name || approval.name || approval.id, 'approve')
      message.success('Decision approved')
      onDecision()
    } catch (err) {
      message.error('Failed to approve: ' + (err?.response?.data?.detail || err.message || 'Unknown error'))
    } finally {
      setDeciding(false)
    }
  }

  const handleReject = () => {
    Modal.confirm({
      title: 'Reject this decision?',
      icon: <ExclamationCircleOutlined />,
      content: 'This will instruct the agent to abort the planned action.',
      okText: 'Reject',
      okType: 'danger',
      cancelText: 'Cancel',
      onOk: async () => {
        setDeciding(true)
        try {
          await postApprove(approval.alarm_name || approval.name || approval.id, 'reject')
          message.success('Decision rejected')
          onDecision()
        } catch (err) {
          message.error('Failed to reject: ' + (err?.response?.data?.detail || err.message || 'Unknown error'))
        } finally {
          setDeciding(false)
        }
      },
    })
  }

  return (
    <Card
      bordered={false}
      style={{
        borderRadius: 8,
        borderLeft: `4px solid ${borderColor}`,
        marginBottom: 0,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
            {isPending && (
              <Badge
                status="processing"
                text={<span style={{ fontSize: 11, color: '#FA8C16', fontWeight: 600 }}>PENDING</span>}
                color="#FA8C16"
              />
            )}
            {isApproved && (
              <Tag icon={<CheckCircleOutlined />} color="success">Approved</Tag>
            )}
            {isRejected && (
              <Tag icon={<CloseCircleOutlined />} color="error">Rejected</Tag>
            )}
            {approval.severity && (
              <Tag color={
                approval.severity === 'critical' ? 'red'
                : approval.severity === 'high' ? 'orange'
                : approval.severity === 'medium' ? 'gold'
                : 'default'
              }>
                {approval.severity}
              </Tag>
            )}
          </div>

          <div style={{ fontSize: 16, fontWeight: 600, color: '#1f1f1f', marginBottom: 2 }}>
            {approval.title || approval.alarm_name || approval.name || 'Approval Required'}
          </div>

          {approval.description && (
            <div style={{ fontSize: 13, color: '#595959', marginTop: 4 }}>
              {approval.description}
            </div>
          )}

          {(approval.sop || approval.action) && (
            <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {approval.sop && (
                <Tooltip title="Standard Operating Procedure">
                  <Tag icon={<InfoCircleOutlined />}>
                    SOP: {approval.sop.split('/').pop()?.replace('.md', '') || approval.sop}
                  </Tag>
                </Tooltip>
              )}
              {approval.action && (
                <Tooltip title="Proposed action">
                  <Tag color="blue">{approval.action}</Tag>
                </Tooltip>
              )}
            </div>
          )}

          {approval.timestamp && (
            <div style={{ fontSize: 11, color: '#9E9E9E', marginTop: 6 }}>
              <ClockCircleOutlined style={{ marginRight: 4 }} />
              {new Date(approval.timestamp).toLocaleString()}
            </div>
          )}
        </div>
      </div>

      <Divider style={{ margin: '12px 0' }} />

      {/* Reasoning / Evidence / Consequences sections */}
      {(approval.reasoning || approval.ai_reasoning) && (
        <SectionBlock
          type="reasoning"
          content={approval.reasoning || approval.ai_reasoning}
        />
      )}
      {(approval.evidence || approval.supporting_data) && (
        <SectionBlock
          type="evidence"
          content={approval.evidence || approval.supporting_data}
        />
      )}
      {(approval.consequences || approval.risks || approval.impact) && (
        <SectionBlock
          type="consequences"
          content={approval.consequences || approval.risks || approval.impact}
        />
      )}

      {/* Context metrics if any */}
      {approval.context && Object.keys(approval.context).length > 0 && (
        <div
          style={{
            background: '#FAFAFA',
            border: '1px solid #F0F0F0',
            borderRadius: 6,
            padding: '8px 12px',
            marginBottom: 10,
          }}
        >
          <div style={{ fontSize: 11, color: '#8c8c8c', fontWeight: 600, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.8 }}>
            Context
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {Object.entries(approval.context).map(([k, v]) => (
              <div key={k} style={{ fontSize: 12 }}>
                <span style={{ color: '#8c8c8c' }}>{k}: </span>
                <span style={{ fontWeight: 500 }}>{String(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action buttons */}
      {isPending && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <Button
            type="primary"
            icon={<CheckCircleOutlined />}
            onClick={handleApprove}
            loading={deciding}
            style={{ flex: 1 }}
          >
            Approve
          </Button>
          <Button
            danger
            icon={<CloseCircleOutlined />}
            onClick={handleReject}
            loading={deciding}
            style={{ flex: 1 }}
          >
            Reject
          </Button>
        </div>
      )}

      {(isApproved || isRejected) && approval.decided_at && (
        <div style={{ fontSize: 11, color: '#9E9E9E', marginTop: 8 }}>
          <CheckCircleOutlined style={{ marginRight: 4 }} />
          Decided: {new Date(approval.decided_at).toLocaleString()}
          {approval.decided_by && ` by ${approval.decided_by}`}
        </div>
      )}
    </Card>
  )
}

const Approvals = () => {
  const [approvals, setApprovals] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('pending')

  const loadApprovals = () => {
    getApprovals()
      .then(data => {
        const list = data?.approvals || data?.pending || (Array.isArray(data) ? data : [])
        setApprovals(list)
        setLoading(false)
        setError(null)
      })
      .catch(err => {
        setError(err.message || 'Failed to load approvals')
        setLoading(false)
      })
  }

  useEffect(() => {
    loadApprovals()
    const t = setInterval(loadApprovals, 30000)
    return () => clearInterval(t)
  }, [])

  const pendingList = approvals.filter(a => !a.status || a.status === 'pending')
  const approvedList = approvals.filter(a => a.status === 'approved')
  const rejectedList = approvals.filter(a => a.status === 'rejected' || a.status === 'denied')

  const filteredList = filter === 'pending' ? pendingList
    : filter === 'approved' ? approvedList
    : filter === 'rejected' ? rejectedList
    : approvals

  return (
    <div>
      {error && (
        <Alert
          type="error"
          message={error}
          closable
          style={{ marginBottom: 16, borderRadius: 6 }}
        />
      )}

      {/* Filter bar */}
      <Card bordered={false} style={{ borderRadius: 8, marginBottom: 16 }} bodyStyle={{ padding: '12px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 600, fontSize: 14 }}>Filter:</span>
          <Space>
            {[
              { key: 'pending', label: 'Pending', count: pendingList.length, color: '#FA8C16' },
              { key: 'approved', label: 'Approved', count: approvedList.length, color: '#52c41a' },
              { key: 'rejected', label: 'Rejected', count: rejectedList.length, color: '#ff4d4f' },
              { key: 'all', label: 'All', count: approvals.length, color: '#8c8c8c' },
            ].map(f => (
              <Button
                key={f.key}
                type={filter === f.key ? 'primary' : 'default'}
                size="small"
                onClick={() => setFilter(f.key)}
                style={filter !== f.key ? { borderColor: f.color, color: f.color } : {}}
              >
                {f.label}
                {f.count > 0 && (
                  <Badge
                    count={f.count}
                    size="small"
                    style={{
                      marginLeft: 4,
                      background: filter === f.key ? 'rgba(255,255,255,0.3)' : f.color,
                    }}
                  />
                )}
              </Button>
            ))}
          </Space>
        </div>
      </Card>

      {/* Approval cards */}
      {loading ? (
        <Row gutter={[16, 16]}>
          {[1, 2, 3].map(k => (
            <Col xs={24} lg={12} key={k}>
              <Card bordered={false} style={{ borderRadius: 8 }}>
                <Skeleton active paragraph={{ rows: 4 }} />
              </Card>
            </Col>
          ))}
        </Row>
      ) : filteredList.length === 0 ? (
        <Card bordered={false} style={{ borderRadius: 8, textAlign: 'center' }}>
          <Empty
            image={
              filter === 'pending'
                ? <CheckCircleOutlined style={{ fontSize: 48, color: '#52c41a' }} />
                : Empty.PRESENTED_IMAGE_SIMPLE
            }
            description={
              filter === 'pending'
                ? <span style={{ color: '#52c41a', fontWeight: 500 }}>No pending decisions — all clear!</span>
                : `No ${filter} approvals`
            }
            style={{ padding: '32px 0' }}
          />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {filteredList.map((approval, i) => (
            <Col xs={24} lg={12} key={approval.id || approval.alarm_name || i}>
              <ApprovalCard approval={approval} onDecision={loadApprovals} />
            </Col>
          ))}
        </Row>
      )}
    </div>
  )
}

export default Approvals
