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
