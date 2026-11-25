import { useState, useEffect } from 'react'
import {
  Row, Col, Card, Skeleton, Empty,
  Timeline, Progress,
} from 'antd'
import {
  ThunderboltOutlined,
  TrophyOutlined,
} from '@ant-design/icons'
import { getAnraTrackRecord, getAgentsReasoning } from '../services/api'

// Remediations this agent proposed and the Network Change Agent ran after your
// approval, counted from DeploymentPlans. Fix time runs from approval to the
// plan finishing. Values are "—" until there is something to measure.
const TrackRecord = ({ record, loading }) => {
  if (loading) return <Skeleton active paragraph={{ rows: 3 }} />
  if (!record) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No track record data" />

  const rate = record.sop_success_rate
  const ratePct = rate == null ? null : Math.round(rate * 100)
  const fixTime = record.avg_mttr_auto_seconds == null
    ? '—'
    : record.avg_mttr_auto_seconds < 120
      ? `${record.avg_mttr_auto_seconds}s`
      : `${Math.round(record.avg_mttr_auto_seconds / 60)}m`

  const tiles = [
    { value: record.incidents_handled ?? 0, label: 'Approved remediations', color: '#1890FF', bg: '#F0F5FF' },
    { value: record.completed ?? record.auto_resolved ?? 0, label: 'Completed', color: '#52c41a', bg: '#F6FFED' },
    { value: record.escalated ?? 0, label: 'Failed', color: '#FA8C16', bg: '#FFF7E6' },
    { value: fixTime, label: 'Avg fix time', color: '#722ed1', bg: '#F9F0FF' },
  ]

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {tiles.map(t => (
          <Col xs={12} sm={6} key={t.label}>
            <Card size="small" bordered={false} style={{ textAlign: 'center', background: t.bg, borderRadius: 8 }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: t.color }}>{t.value}</div>
              <div style={{ fontSize: 11, color: '#8c8c8c' }}>{t.label}</div>
            </Card>
          </Col>
        ))}
      </Row>
      <div style={{ marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 500 }}>SOP success rate</span>
        <span style={{ float: 'right', fontSize: 13, fontWeight: 700, color: '#1890FF' }}>
          {ratePct == null ? '—' : `${ratePct}%`}
        </span>
      </div>
      <Progress percent={ratePct ?? 0} strokeColor="#1890FF" showInfo={false} style={{ marginBottom: 0 }} />
    </div>
  )
}

const AnraPage = () => {
  const [trackRecord, setTrackRecord] = useState(null)
  const [trackLoading, setTrackLoading] = useState(true)
  const [reasoning, setReasoning] = useState([])
  const [reasoningLoading, setReasoningLoading] = useState(true)

  const loadData = () => {
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

  return (
    <div>
      <Row gutter={[16, 16]}>
        {/* Reasoning Feed */}
        <Col xs={24}>
          <Card
            title={
              <span>
                <ThunderboltOutlined style={{ marginRight: 8, color: '#7C4DFF' }} />
                Assurance Agent Reasoning
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
                        {entry.agent && <span>[Network Assurance Agent] </span>}
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
