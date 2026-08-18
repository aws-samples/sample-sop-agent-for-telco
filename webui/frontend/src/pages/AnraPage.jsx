import { useState, useEffect } from 'react'
import {
  Row, Col, Card, Tag, Skeleton, Empty, Alert, Statistic,
  Timeline, Steps, Descriptions, Progress, Button,
} from 'antd'
import {
  SafetyCertificateOutlined,
  FireOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  EyeOutlined,
  HistoryOutlined,
  TrophyOutlined,
  LinkOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getAnraIncidentCurrent, getAnraTrackRecord, getAgentsReasoning } from '../services/api'

const OODA_STEPS = [
  { title: 'Observe', icon: <EyeOutlined />, color: '#1890FF', description: 'Ingest alarms, metrics, logs' },
  { title: 'Orient', icon: <ThunderboltOutlined />, color: '#722ed1', description: 'Classify, correlate, prioritise' },
  { title: 'Decide', icon: <SafetyCertificateOutlined />, color: '#FA8C16', description: 'Select SOP, get approvals' },
  { title: 'Act', icon: <CheckCircleOutlined />, color: '#52c41a', description: 'Execute remediation steps' },
]

const OODA_STATE_INDEX = {
  observe: 0,
  orient: 1,
  decide: 2,
  act: 3,
}

const OodaChain = ({ currentState, loading }) => {
  const currentIdx = OODA_STATE_INDEX[currentState?.toLowerCase()] ?? -1

  if (loading) return <Skeleton active paragraph={{ rows: 2 }} />

  return (
    <div>
      <Steps
        current={currentIdx}
        size="small"
        style={{ marginBottom: 16 }}
        items={OODA_STEPS.map((step, i) => ({
          title: step.title,
          description: step.description,
          icon: (
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                background: i <= currentIdx ? step.color : '#f0f0f0',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: i <= currentIdx ? '#fff' : '#bbb',
                fontSize: 14,
                transition: 'all 0.3s',
              }}
            >
              {step.icon}
            </div>
          ),
        }))}
      />
      {currentState && (
        <div
          style={{
            textAlign: 'center',
            fontSize: 13,
            color: '#6A1B9A',
            fontWeight: 500,
            background: '#F3E5F5',
            borderRadius: 6,
            padding: '6px 12px',
            display: 'inline-block',
          }}
        >
          Current phase: <strong>{currentState}</strong>
        </div>
      )}
    </div>
  )
}

const IncidentCard = ({ incident, loading }) => {
  const navigate = useNavigate()

  if (loading) return <Skeleton active paragraph={{ rows: 4 }} />

  if (!incident || !incident.active) {
    return (
      <div
        style={{
          textAlign: 'center',
          padding: '32px 0',
          color: '#52c41a',
        }}
      >
        <CheckCircleOutlined style={{ fontSize: 48, color: '#52c41a', marginBottom: 12, display: 'block' }} />
        <div style={{ fontSize: 18, fontWeight: 600, color: '#52c41a', marginBottom: 8 }}>All Clear</div>
        <div style={{ fontSize: 13, color: '#8c8c8c' }}>No active incidents — system is operating normally</div>
      </div>
    )
  }

  return (
    <div>
      <Alert
        type="error"
        showIcon
        icon={<FireOutlined />}
        message={
          <span style={{ fontWeight: 600 }}>
            Active Incident {incident.incident_id && <Tag color="red" style={{ marginLeft: 8 }}>{incident.incident_id}</Tag>}
          </span>
        }
        description={incident.root_cause && typeof incident.root_cause === 'object' ? incident.root_cause.description || JSON.stringify(incident.root_cause) : incident.root_cause}
        style={{ marginBottom: 16, borderRadius: 6 }}
      />

      <Descriptions column={1} size="small" bordered>
        {incident.sop && (
          <Descriptions.Item label="SOP">
            <code style={{ fontSize: 12, background: '#f5f5f5', padding: '2px 6px', borderRadius: 3 }}>
              {typeof incident.sop === 'object' ? incident.sop.name || 'unknown' : incident.sop}
            </code>
          </Descriptions.Item>
        )}
        {incident.ooda_state && (
          <Descriptions.Item label="OODA Phase">
            <Tag color="purple">{incident.ooda_state}</Tag>
          </Descriptions.Item>
        )}
        {incident.success_criteria && (
          <Descriptions.Item label="Success Criteria">
            <span style={{ fontSize: 12 }}>{incident.success_criteria}</span>
          </Descriptions.Item>
        )}
      </Descriptions>

      {incident.incident_id && (
        <Button
          type="link"
          icon={<LinkOutlined />}
          size="small"
          style={{ marginTop: 12, paddingLeft: 0 }}
          onClick={() => navigate(`/incidents/${incident.incident_id}`)}
        >
          View incident timeline
        </Button>
      )}
    </div>
  )
}

const TrackRecord = ({ record, loading }) => {
  if (loading) return <Skeleton active paragraph={{ rows: 3 }} />
  if (!record) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No track record data" />

  const autoResolveRate = record.incidents_handled > 0
    ? Math.round((record.auto_resolved / record.incidents_handled) * 100)
    : 0
  const mttrMinutes = record.avg_mttr_auto_seconds
    ? Math.round(record.avg_mttr_auto_seconds / 60)
    : null

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small" bordered={false} style={{ textAlign: 'center', background: '#F0F5FF', borderRadius: 8 }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#1890FF' }}>
              {record.incidents_handled ?? 0}
            </div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>Total incidents</div>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" bordered={false} style={{ textAlign: 'center', background: '#F6FFED', borderRadius: 8 }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#52c41a' }}>
              {record.auto_resolved ?? 0}
            </div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>Auto-resolved</div>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" bordered={false} style={{ textAlign: 'center', background: '#FFF7E6', borderRadius: 8 }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#FA8C16' }}>
              {record.escalated ?? 0}
            </div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>Escalated</div>
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" bordered={false} style={{ textAlign: 'center', background: '#F9F0FF', borderRadius: 8 }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#722ed1' }}>
              {mttrMinutes !== null ? `${mttrMinutes}m` : '—'}
            </div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>Avg MTTR (auto)</div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12}>
          <div style={{ marginBottom: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>Auto-resolution rate</span>
            <span style={{ float: 'right', fontSize: 13, fontWeight: 700, color: autoResolveRate >= 70 ? '#52c41a' : '#FA8C16' }}>
              {autoResolveRate}%
            </span>
          </div>
          <Progress
            percent={autoResolveRate}
            strokeColor={autoResolveRate >= 70 ? '#52c41a' : '#FA8C16'}
            showInfo={false}
            style={{ marginBottom: 0 }}
          />
        </Col>
        {record.sop_success_rate !== undefined && (
          <Col xs={24} sm={12}>
            <div style={{ marginBottom: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 500 }}>SOP success rate</span>
              <span style={{ float: 'right', fontSize: 13, fontWeight: 700, color: '#1890FF' }}>
                {Math.round((record.sop_success_rate ?? 0) * 100)}%
              </span>
            </div>
            <Progress
              percent={Math.round((record.sop_success_rate ?? 0) * 100)}
              strokeColor="#1890FF"
              showInfo={false}
              style={{ marginBottom: 0 }}
            />
          </Col>
        )}
      </Row>
    </div>
  )
}

const AnraPage = () => {
  const [incident, setIncident] = useState(null)
  const [incidentLoading, setIncidentLoading] = useState(true)
  const [trackRecord, setTrackRecord] = useState(null)
  const [trackLoading, setTrackLoading] = useState(true)
  const [reasoning, setReasoning] = useState([])
  const [reasoningLoading, setReasoningLoading] = useState(true)

  const loadData = () => {
    getAnraIncidentCurrent()
      .then(data => { setIncident(data); setIncidentLoading(false) })
      .catch(() => setIncidentLoading(false))

    getAnraTrackRecord()
      .then(data => { setTrackRecord(data); setTrackLoading(false) })
      .catch(() => setTrackLoading(false))
  }

  const loadReasoning = () => {
    getAgentsReasoning()
      .then(data => {
        const anraEntries = (data?.entries || []).filter(e =>
          !e.agent || e.agent.toLowerCase().includes('anra') || e.agent.toLowerCase().includes('remediation')
        )
        setReasoning(anraEntries)
        setReasoningLoading(false)
      })
      .catch(() => setReasoningLoading(false))
  }

  useEffect(() => {
    loadData()
    loadReasoning()
    const dataTimer = setInterval(loadData, 30000)
    const reasoningTimer = setInterval(loadReasoning, 5000)
    return () => {
      clearInterval(dataTimer)
      clearInterval(reasoningTimer)
    }
  }, [])

  const ooda_state = incident?.ooda_state

  return (
    <div>
      <Row gutter={[16, 16]}>
        {/* OODA Chain */}
        <Col xs={24}>
          <Card
            title={
              <span>
                <SafetyCertificateOutlined style={{ marginRight: 8, color: '#722ed1' }} />
                OODA Reasoning Chain
              </span>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
          >
            <OodaChain currentState={ooda_state} loading={incidentLoading} />
          </Card>
        </Col>

        {/* Active Incident */}
        <Col xs={24} lg={14}>
          <Card
            title={
              <span>
                <FireOutlined style={{ marginRight: 8, color: incident?.active ? '#ff4d4f' : '#52c41a' }} />
                Active Incident
              </span>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
          >
            <IncidentCard incident={incident} loading={incidentLoading} />
          </Card>
        </Col>

        {/* Reasoning Feed */}
        <Col xs={24} lg={10}>
          <Card
            title={
              <span>
                <ThunderboltOutlined style={{ marginRight: 8, color: '#7C4DFF' }} />
                ANRA Reasoning
              </span>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
            bodyStyle={{ maxHeight: 360, overflowY: 'auto', padding: '12px 16px' }}
          >
            {reasoningLoading ? (
              <Skeleton active paragraph={{ rows: 3 }} />
            ) : reasoning.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No reasoning data" />
            ) : (
              <Timeline
                mode="left"
                items={reasoning.slice().reverse().slice(0, 20).map((entry, i) => ({
                  key: i,
                  color: entry.type === 'act' ? '#52c41a'
                    : entry.type === 'decide' ? '#FA8C16'
                    : entry.type === 'observe' ? '#1890FF'
                    : '#722ed1',
                  label: entry.timestamp
                    ? new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                    : '',
                  children: (
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: '#6A1B9A', marginBottom: 2 }}>
                        {entry.agent && <span>[{entry.agent}] </span>}
                        {entry.message}
                      </div>
                      {entry.detail && (
                        <div style={{ fontSize: 11, color: '#8c8c8c' }}>{entry.detail}</div>
                      )}
                    </div>
                  ),
                }))}
              />
            )}
          </Card>
        </Col>

        {/* Track Record */}
        <Col xs={24}>
          <Card
            title={
              <span>
                <TrophyOutlined style={{ marginRight: 8, color: '#FA8C16' }} />
                Track Record
              </span>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
          >
            <TrackRecord record={trackRecord} loading={trackLoading} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default AnraPage
