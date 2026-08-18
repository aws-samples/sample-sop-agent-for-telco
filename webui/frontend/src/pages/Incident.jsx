import { useState, useEffect } from 'react'
import {
  Row, Col, Card, Tag, Skeleton, Empty, Alert, Timeline,
  Descriptions, Button, Divider, Badge,
} from 'antd'
import {
  ArrowLeftOutlined,
  FireOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  BookOutlined,
  HistoryOutlined,
  BulbOutlined,
  ExclamationCircleOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  EyeOutlined,
} from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { getAnraIncident } from '../services/api'

const STEP_COLORS = {
  detect: '#1890FF',
  observe: '#1890FF',
  classify: '#722ed1',
  orient: '#722ed1',
  decide: '#FA8C16',
  approve: '#FA8C16',
  execute: '#52c41a',
  act: '#52c41a',
  verify: '#13c2c2',
  resolve: '#52c41a',
  escalate: '#ff4d4f',
  rollback: '#ff4d4f',
  error: '#ff4d4f',
  failed: '#ff4d4f',
}

const STEP_ICONS = {
  detect: <EyeOutlined />,
  observe: <EyeOutlined />,
  classify: <ThunderboltOutlined />,
  orient: <ThunderboltOutlined />,
  decide: <SafetyCertificateOutlined />,
  approve: <SafetyCertificateOutlined />,
  execute: <CheckCircleOutlined />,
  act: <CheckCircleOutlined />,
  verify: <CheckCircleOutlined />,
  resolve: <CheckCircleOutlined />,
  escalate: <ExclamationCircleOutlined />,
  rollback: <ExclamationCircleOutlined />,
}

const getStepColor = (step) => {
  if (!step) return '#8c8c8c'
  const key = step.type?.toLowerCase() || step.action?.toLowerCase() || ''
  return Object.entries(STEP_COLORS).find(([k]) => key.includes(k))?.[1] || '#8c8c8c'
}

const getStepIcon = (step) => {
  if (!step) return <ClockCircleOutlined />
  const key = step.type?.toLowerCase() || step.action?.toLowerCase() || ''
  return Object.entries(STEP_ICONS).find(([k]) => key.includes(k))?.[1] || <ClockCircleOutlined />
}

const LearningBlock = ({ learning }) => {
  if (!learning) return null

  const items = Array.isArray(learning)
    ? learning
    : typeof learning === 'string'
    ? [learning]
    : Object.entries(learning).map(([k, v]) => `${k}: ${v}`)

  return (
    <div>
      {items.map((item, i) => (
        <div
          key={i}
          style={{
            background: '#E8F5E9',
            border: '1px solid #A5D6A7',
            borderRadius: 6,
            padding: '10px 14px',
            marginBottom: 8,
            display: 'flex',
            alignItems: 'flex-start',
            gap: 10,
          }}
        >
          <BulbOutlined style={{ color: '#2E7D32', marginTop: 2, flexShrink: 0 }} />
          <span style={{ fontSize: 13, color: '#1B5E20', lineHeight: 1.6 }}>{item}</span>
        </div>
      ))}
    </div>
  )
}

const Incident = () => {
  const { id } = useParams()
  const navigate = useNavigate()
  const [incident, setIncident] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadIncident = () => {
    if (!id) return
    getAnraIncident(id)
      .then(data => { setIncident(data); setLoading(false); setError(null) })
      .catch(err => {
        setError(err?.response?.status === 404 ? `Incident "${id}" not found` : (err.message || 'Failed to load incident'))
        setLoading(false)
      })
  }

  useEffect(() => {
    loadIncident()
    const t = setInterval(loadIncident, 30000)
    return () => clearInterval(t)
  }, [id])

  if (loading) {
    return (
      <div>
        <Button icon={<ArrowLeftOutlined />} type="text" onClick={() => navigate('/anra')} style={{ marginBottom: 16 }}>
          Back to ANRA
        </Button>
        <Row gutter={[16, 16]}>
          {[1, 2].map(k => (
            <Col xs={24} lg={12} key={k}>
              <Card bordered={false} style={{ borderRadius: 8 }}>
                <Skeleton active paragraph={{ rows: 6 }} />
              </Card>
            </Col>
          ))}
        </Row>
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <Button icon={<ArrowLeftOutlined />} type="text" onClick={() => navigate('/anra')} style={{ marginBottom: 16 }}>
          Back to ANRA
        </Button>
        <Alert
          type="error"
          showIcon
          message="Incident not found"
          description={error}
          action={
            <Button size="small" onClick={loadIncident}>Retry</Button>
          }
        />
      </div>
    )
  }

  if (!incident) {
    return (
      <div>
        <Button icon={<ArrowLeftOutlined />} type="text" onClick={() => navigate('/anra')} style={{ marginBottom: 16 }}>
          Back to ANRA
        </Button>
        <Empty description="No incident data" />
      </div>
    )
  }

  const timeline = incident.timeline || []
  const learning = incident.learning
  const isResolved = incident.resolved

  const durationMs = timeline.length >= 2
    ? new Date(timeline[timeline.length - 1]?.timestamp) - new Date(timeline[0]?.timestamp)
    : null
  const durationMin = durationMs ? Math.round(durationMs / 60000) : null

  return (
    <div>
      {/* Back button */}
      <Button
        icon={<ArrowLeftOutlined />}
        type="text"
        onClick={() => navigate('/anra')}
        style={{ marginBottom: 16, paddingLeft: 0 }}
      >
        Back to ANRA
      </Button>

      {/* Header card */}
      <Card
        bordered={false}
        style={{
          borderRadius: 8,
          marginBottom: 16,
          borderLeft: `4px solid ${isResolved ? '#52c41a' : '#ff4d4f'}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              {isResolved ? (
                <Tag icon={<CheckCircleOutlined />} color="success">Resolved</Tag>
              ) : (
                <Badge
                  status="processing"
                  text={<span style={{ color: '#ff4d4f', fontWeight: 600, fontSize: 12 }}>ACTIVE</span>}
                  color="#ff4d4f"
                />
              )}
              <Tag>{incident.id}</Tag>
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#1f1f1f', marginBottom: 4 }}>
              {incident.root_cause || incident.title || `Incident ${incident.id}`}
            </div>
            {incident.sop && (
              <div style={{ fontSize: 13, color: '#595959' }}>
                SOP: <code style={{ background: '#f5f5f5', padding: '1px 6px', borderRadius: 3 }}>{incident.sop}</code>
              </div>
            )}
          </div>
          <div style={{ textAlign: 'right' }}>
            {durationMin !== null && (
              <div>
                <div style={{ fontSize: 24, fontWeight: 700, color: '#1890FF' }}>{durationMin}m</div>
                <div style={{ fontSize: 11, color: '#8c8c8c' }}>Duration</div>
              </div>
            )}
          </div>
        </div>

        {/* Metadata */}
        <Divider style={{ margin: '12px 0' }} />
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}>
          {incident.start_time && (
            <Descriptions.Item label="Started">
              <span style={{ fontSize: 12 }}>{new Date(incident.start_time).toLocaleString()}</span>
            </Descriptions.Item>
          )}
          {incident.resolved_time && (
            <Descriptions.Item label="Resolved">
              <span style={{ fontSize: 12 }}>{new Date(incident.resolved_time).toLocaleString()}</span>
            </Descriptions.Item>
          )}
          {incident.ooda_state && (
            <Descriptions.Item label="Final OODA">
              <Tag color="purple">{incident.ooda_state}</Tag>
            </Descriptions.Item>
          )}
          {incident.success_criteria && (
            <Descriptions.Item label="Success Criteria" span={3}>
              <span style={{ fontSize: 12 }}>{incident.success_criteria}</span>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <Row gutter={[16, 16]}>
        {/* Timeline */}
        <Col xs={24} lg={14}>
          <Card
            title={
              <span>
                <HistoryOutlined style={{ marginRight: 8, color: '#1890FF' }} />
                Incident Timeline
              </span>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
          >
            {timeline.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No timeline data" />
            ) : (
              <Timeline
                mode="left"
                items={timeline.map((step, i) => {
                  const color = getStepColor(step)
                  const icon = getStepIcon(step)
                  const timeStr = step.timestamp
                    ? new Date(step.timestamp).toLocaleString([], {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })
                    : ''

                  return {
                    key: i,
                    color,
                    dot: (
                      <div
                        style={{
                          width: 24,
                          height: 24,
                          borderRadius: '50%',
                          background: color,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: '#fff',
                          fontSize: 11,
                        }}
                      >
                        {icon}
                      </div>
                    ),
                    label: <span style={{ fontSize: 11, color: '#9E9E9E', whiteSpace: 'nowrap' }}>{timeStr}</span>,
                    children: (
                      <div style={{ paddingBottom: 4 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
                          {(step.type || step.action) && (
                            <Tag
                              style={{
                                fontSize: 10,
                                color,
                                border: `1px solid ${color}`,
                                background: `${color}18`,
                                margin: 0,
                              }}
                            >
                              {step.type || step.action}
                            </Tag>
                          )}
                          {step.status && (
                            <Tag
                              style={{ margin: 0, fontSize: 10 }}
                              color={step.status === 'success' || step.status === 'completed' ? 'green'
                                : step.status === 'failed' || step.status === 'error' ? 'red'
                                : 'default'}
                            >
                              {step.status}
                            </Tag>
                          )}
                          {step.agent && (
                            <span style={{ fontSize: 11, fontWeight: 600, color: '#6A1B9A' }}>[{step.agent}]</span>
                          )}
                        </div>

                        <div style={{ fontSize: 13, fontWeight: 500, color: '#1f1f1f', marginBottom: step.detail ? 4 : 0 }}>
                          {step.message || step.description || step.summary}
                        </div>

                        {step.detail && (
                          <div
                            style={{
                              fontSize: 12,
                              color: '#595959',
                              background: '#FAFAFA',
                              borderRadius: 4,
                              padding: '4px 8px',
                              marginTop: 4,
                              whiteSpace: 'pre-wrap',
                            }}
                          >
                            {step.detail}
                          </div>
                        )}

                        {step.output && (
                          <div
                            style={{
                              fontSize: 11,
                              color: '#8c8c8c',
                              fontFamily: 'monospace',
                              background: '#f5f5f5',
                              borderRadius: 4,
                              padding: '4px 8px',
                              marginTop: 4,
                              maxHeight: 80,
                              overflow: 'hidden',
                              whiteSpace: 'pre-wrap',
                            }}
                          >
                            {step.output}
                          </div>
                        )}
                      </div>
                    ),
                  }
                })}
              />
            )}
          </Card>
        </Col>

        {/* Learning */}
        <Col xs={24} lg={10}>
          <Card
            title={
              <span>
                <BookOutlined style={{ marginRight: 8, color: '#2E7D32' }} />
                Post-Incident Learning
              </span>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
          >
            {learning ? (
              <LearningBlock learning={learning} />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  isResolved
                    ? 'No learning notes captured'
                    : 'Learning will be captured after resolution'
                }
              />
            )}
          </Card>

          {/* Outcome summary */}
          {(incident.root_cause || incident.resolution_note) && (
            <Card
              title={
                <span>
                  <SafetyCertificateOutlined style={{ marginRight: 8, color: '#FA8C16' }} />
                  Resolution Summary
                </span>
              }
              bordered={false}
              style={{ borderRadius: 8, marginTop: 16 }}
            >
              {incident.root_cause && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#8c8c8c', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 6 }}>
                    Root Cause
                  </div>
                  <div style={{ fontSize: 13, color: '#1f1f1f', lineHeight: 1.6 }}>
                    {incident.root_cause}
                  </div>
                </div>
              )}
              {incident.resolution_note && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#8c8c8c', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 6 }}>
                    Resolution
                  </div>
                  <div style={{ fontSize: 13, color: '#1f1f1f', lineHeight: 1.6 }}>
                    {incident.resolution_note}
                  </div>
                </div>
              )}
            </Card>
          )}
        </Col>
      </Row>
    </div>
  )
}

export default Incident
