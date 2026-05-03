import { useState, useEffect } from 'react'
import { Card, Table, Tag, Badge, Drawer, Descriptions, Spin, Alert, Row, Col, Statistic } from 'antd'
import { AlertOutlined, CheckCircleOutlined, ClockCircleOutlined } from '@ant-design/icons'
import axios from 'axios'
import RemediationPipeline from '../components/RemediationPipeline'
import ActivityFeed from '../components/ActivityFeed'

const SEV = { critical: 'red', warning: 'orange', info: 'blue' }

const Alarms = () => {
  const [alarms, setAlarms] = useState([])
  const [execs, setExecs] = useState([])
  const [corrs, setCorrs] = useState([])
  const [events, setEvents] = useState([])
  const [activity, setActivity] = useState([])
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)
  const [ready, setReady] = useState(false)

  const load = () => {
    Promise.all([
      axios.get('/api/alarms'),
      axios.get('/api/executions'),
      axios.get('/api/correlations'),
      axios.get('/api/events?window=300'),
      axios.get('/api/activity?limit=40'),
    ])
      .then(([a, e, c, ev, act]) => {
        setAlarms(a.data.alarms || [])
        setExecs(e.data.executions || [])
        setCorrs(c.data.correlations || [])
        setEvents(ev.data.events || [])
        setActivity(act.data.activity || [])
        setError(null)
      })
      .catch((e) => setError(e.message))
      .finally(() => setReady(true))
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [])

  const suppressed = corrs.filter(c => c.action === 'suppress').length
  const successRate = execs.length ? Math.round(execs.filter(e => e.result === 'completed' || e.result === 'success').length / execs.length * 100) : 0
  const activeStage = activity.length > 0 ? activity[activity.length - 1].stage : null

  if (error) return <Alert type="error" message={error} />
  if (!ready) return <Spin style={{ display: 'block', margin: '120px auto' }} />

  return (
    <div>
      {/* KPI Cards */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col span={5}><Card bordered={false} size="small"><Statistic title="Active Alarms" value={alarms.length} prefix={<AlertOutlined />}
          valueStyle={alarms.length > 0 ? { color: '#cf1322' } : {}} /></Card></Col>
        <Col span={5}><Card bordered={false} size="small"><Statistic title="Suppressed" value={suppressed} valueStyle={{ color: '#722ed1' }} /></Card></Col>
        <Col span={5}><Card bordered={false} size="small"><Statistic title="SOPs Executed" value={execs.length} prefix={<CheckCircleOutlined />} /></Card></Col>
        <Col span={5}><Card bordered={false} size="small"><Statistic title="Success Rate" value={successRate} suffix="%" valueStyle={{ color: successRate >= 80 ? '#3f8600' : '#cf1322' }} /></Card></Col>
        <Col span={4}><Card bordered={false} size="small"><Statistic title="Events (5m)" value={events.length} prefix={<ClockCircleOutlined />} /></Card></Col>
      </Row>

      {/* Remediation Pipeline */}
      <Card bordered={false} style={{ marginBottom: 16, borderRadius: 12, background: 'linear-gradient(135deg, #fafafa 0%, #f0f5ff 100%)' }}>
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>Remediation Pipeline</div>
        <RemediationPipeline activeStage={activeStage} />
      </Card>

      {/* Live Activity Feed */}
      <Card bordered={false} title={<span>Live Activity {activity.length > 0 && <Badge status="processing" />}</span>}
        style={{ marginBottom: 16, borderRadius: 12 }}>
        <ActivityFeed activity={activity} />
      </Card>

      {/* Active Alarms + Correlations */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card bordered={false} title={<span>Active Alarms <Badge count={alarms.length} style={{ marginLeft: 8 }} /></span>}
            style={{ borderRadius: 12, minHeight: 200 }}>
            {alarms.length === 0 ? (
              <div style={{ color: '#bfbfbf', textAlign: 'center', padding: 24 }}>No active alarms</div>
            ) : alarms.map((a, i) => (
              <div key={`${a.name}-${i}`} onClick={() => setSelected(a)}
                style={{
                  padding: '10px 12px', marginBottom: 8, borderRadius: 8, cursor: 'pointer',
                  border: `1px solid ${a.suppressed ? '#f0f0f0' : SEV[a.severity] === 'red' ? '#ffa39e' : '#ffd591'}`,
                  background: a.suppressed ? '#fafafa' : '#fff',
                  opacity: a.suppressed ? 0.6 : 1,
                }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span style={{ fontSize: 14, fontWeight: 600, color: a.suppressed ? '#999' : '#434343' }}>
                      {a.suppressed ? '○' : '●'} {a.name}
                    </span>
                    {a.suppressed && <Tag color="default" style={{ marginLeft: 8, fontSize: 10 }}>SUPPRESSED</Tag>}
                  </div>
                  <Tag color={SEV[a.severity]}>{a.severity}</Tag>
                </div>
                {a.suppressed ? (
                  <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>symptom of → {a.root_cause}</div>
                ) : (
                  <>
                    <div style={{ fontSize: 11, color: '#666', marginTop: 4 }}>{a.service_impact}</div>
                    {a.sop && <div style={{ fontSize: 10, color: '#1890ff', marginTop: 2 }}>SOP: {a.sop.split('/').pop()}</div>}
                  </>
                )}
              </div>
            ))}
          </Card>
        </Col>
        <Col span={12}>
          <Card bordered={false} title="Correlation Decisions" style={{ borderRadius: 12, minHeight: 200 }}>
            {corrs.length === 0 ? (
              <div style={{ color: '#bfbfbf', textAlign: 'center', padding: 24 }}>No correlations yet</div>
            ) : (
              <Table dataSource={corrs.slice(-10).reverse()} size="small" pagination={false}
                rowKey={(r, i) => `${r.root_cause}-${r.action}-${i}`}
                columns={[
                  { title: 'Action', dataIndex: 'action', width: 80, render: a => <Tag color={a === 'suppress' ? 'purple' : a === 'execute' ? 'green' : 'orange'}>{a}</Tag> },
                  { title: 'Root Cause', dataIndex: 'root_cause', render: t => <b>{t}</b> },
                  { title: 'Symptoms', dataIndex: 'symptoms', render: s => (s || []).map(n => <Tag key={n} style={{ fontSize: 10 }}>{n}</Tag>) },
                  { title: 'Confidence', dataIndex: 'confidence', width: 80, render: c => <Tag color={c === 'high' ? 'green' : 'orange'}>{c}</Tag> },
                ]} />
            )}
          </Card>
        </Col>
      </Row>

      {/* Execution History */}
      <Card bordered={false} title="Execution History" style={{ marginBottom: 16, borderRadius: 12 }}>
        <Table dataSource={execs.slice(-20).reverse()} size="small" pagination={{ pageSize: 8 }}
          rowKey={(r, i) => `${r.sop}-${r.timestamp}-${i}`}
          columns={[
            { title: 'Alarm', dataIndex: 'alarm', render: t => <b>{t}</b> },
            { title: 'SOP', dataIndex: 'sop', ellipsis: true, render: s => s ? s.split('/').pop() : '-' },
            { title: 'Status', dataIndex: 'result', width: 80, render: s => <Tag color={s === 'completed' || s === 'success' ? 'green' : 'red'}>{s}</Tag> },
            { title: 'Correlation', dataIndex: 'correlation', ellipsis: true, render: c => <span style={{ fontSize: 11, color: '#666' }}>{c}</span> },
            { title: 'Time', dataIndex: 'timestamp', width: 80, render: t => t ? new Date(t).toLocaleTimeString() : '-' },
          ]} />
      </Card>

      {/* Demo Trigger Bar */}
      <Card bordered={false} size="small" style={{ borderRadius: 12, background: '#f6f6f6', border: '1px dashed #d9d9d9' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: '#666' }}>Demo — Trigger Alarm:</span>
            {[
              { layer: 'hardware', label: 'Resource Exhaustion', color: '#fa8c16' },
              { layer: 'infra', label: 'UPF PFCP Loss', color: '#722ed1' },
              { layer: 'core', label: 'NF CrashLoop', color: '#1890ff' },
              { layer: 'ran', label: 'AMF-gNB Disconnect', color: '#f5222d' },
            ].map(({ layer, label, color }) => (
              <button key={layer} onClick={() => axios.post(`/api/alarms/trigger/${layer}`).then(() => load())}
                style={{ background: color, color: '#fff', border: 'none', borderRadius: 6, padding: '5px 16px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
                {label}
              </button>
            ))}
          </div>
          <span style={{ fontSize: 11, color: '#999' }}>Triggers flow through the full pipeline above</span>
        </div>
      </Card>

      {/* Alarm Detail Drawer */}
      <Drawer title={selected?.name} open={!!selected} onClose={() => setSelected(null)} width={480}>
        {selected && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="Severity"><Tag color={SEV[selected.severity]}>{selected.severity}</Tag></Descriptions.Item>
            <Descriptions.Item label="Source">{selected.source}</Descriptions.Item>
            <Descriptions.Item label="Impact">{selected.service_impact}</Descriptions.Item>
            <Descriptions.Item label="Cause">{selected.probable_cause}</Descriptions.Item>
            {selected.value !== undefined && <Descriptions.Item label="Value">{selected.value} (threshold: {selected.threshold})</Descriptions.Item>}
            {selected.sop && <Descriptions.Item label="SOP">{selected.sop}</Descriptions.Item>}
            <Descriptions.Item label="Time">{selected.timestamp}</Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  )
}

export default Alarms
