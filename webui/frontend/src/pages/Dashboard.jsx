import { useState, useEffect } from 'react'
import { Row, Col, Card, Statistic, Table, Tag, Spin, Alert } from 'antd'
import {
  ClusterOutlined,
  ApiOutlined,
  AlertOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import axios from 'axios'
import { Pipeline } from '../components/AnraPipeline'

/** Shape matches GET /api/monitoring-stats; used when the request fails (network / proxy). */
const DEFAULT_MONITORING_STATS = {
  status: 'unavailable',
  detail: null,
  tier1_rules: 0,
  tier2_metrics: 0,
  tier2_ready: 0,
  tier2_pct: 0,
  tier3_cooldown: 300,
  alarm_definitions: 0,
  sources: {},
}

const StatusDot = ({ live }) => (
  <div
    style={{
      position: 'absolute',
      top: 6,
      right: 6,
      width: 8,
      height: 8,
      borderRadius: '50%',
      background: live ? '#52c41a' : '#d9d9d9',
      boxShadow: live ? '0 0 6px #52c41a' : 'none',
    }}
  />
)

const Dashboard = () => {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [monStats, setMonStats] = useState(null)
  const [monStatsFetchError, setMonStatsFetchError] = useState(null)

  const load = () => {
    const mon = axios
      .get('/api/monitoring-stats')
      .then((r) => {
        setMonStatsFetchError(null)
        return r.data
      })
      .catch((err) => {
        setMonStatsFetchError(err.message || 'Failed to load monitoring stats')
        return { ...DEFAULT_MONITORING_STATS, detail: err.message }
      })

    Promise.all([axios.get('/api/topology'), axios.get('/api/alarms'), axios.get('/api/executions'), mon])
      .then(([t, a, e, m]) => {
        setData({ topo: t.data, alarms: a.data, execs: e.data })
        setMonStats(m)
        setError(null)
      })
      .catch((e) => setError(e.message))
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])

  if (error) return <Alert type="error" message={error} />
  if (!data) return <Spin style={{ display: 'block', margin: '100px auto' }} />

  const { topo, alarms, execs } = data
  const s = topo.summary || {}
  const sources = monStats?.sources || {}
  const monOk = monStats?.status === 'ok'
  const monDegraded = monStats?.status === 'degraded'
  const monBanner = Boolean(monStatsFetchError || monDegraded)
  const monBannerText = monStatsFetchError
    ? `Could not reach /api/monitoring-stats: ${monStatsFetchError}`
    : monDegraded && monStats?.detail
      ? `Monitoring coverage is partial: ${monStats.detail}.`
      : 'Monitoring coverage is partial (Tier 2/3 or source checks incomplete).'

  const systemStatus = (() => {
    if (monStatsFetchError) {
      return { text: 'Offline', color: '#cf1322', icon: <CloseCircleOutlined /> }
    }
    if (!monStats) {
      return { text: '—', color: '#8c8c8c', icon: <ExclamationCircleOutlined /> }
    }
    if (monStats.status === 'ok') {
      return { text: 'OK', color: '#3f8600', icon: <CheckCircleOutlined /> }
    }
    if (monDegraded) {
      return { text: 'Degraded', color: '#d48806', icon: <ExclamationCircleOutlined /> }
    }
    return { text: 'Partial', color: '#8c8c8c', icon: <ExclamationCircleOutlined /> }
  })()

  // Build friendly node names from config nodes + k8s nodes
  const configNodes = topo.config_nodes || []
  const k8sNodes = (topo.k8s_nodes || []).map((n) => {
    const cfg = configNodes.find((c) => c.oam_ip === n.ip)
    return {
      ...n,
      friendly: cfg?.name || n.name.split('.')[0].replace('ip-', '').replaceAll('-', '.'),
      nf_pod_count: n.nf_pod_count ?? 0,
    }
  })

  const recentAlarms = (alarms.alarms || []).slice(-5).reverse()
  const recentExecs = (execs.executions || []).slice(-5).reverse()

  return (
    <div>
      {monBanner && (
        <Alert
          type={monStatsFetchError ? 'error' : 'warning'}
          showIcon
          message={monBannerText}
          role="status"
          aria-live="polite"
          style={{ marginBottom: 16 }}
        />
      )}
      <Card
        bordered={false}
        style={{ marginBottom: 16, borderRadius: 12, background: 'linear-gradient(135deg, #fafafa 0%, #f0f5ff 100%)' }}
      >
        <div
          style={{
            fontWeight: 600,
            fontSize: 14,
            marginBottom: 8,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 8,
          }}
        >
          <span>ANRA Pipeline — Detect → Correlate → Remediate</span>
          {monStats && monOk && (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
                color: '#52c41a',
                fontWeight: 600,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: '#52c41a',
                  display: 'inline-block',
                  animation: 'glow 2s infinite',
                }}
              />
              ANRA Live
            </span>
          )}
          {monStats && monStatsFetchError && (
            <span style={{ fontSize: 12, color: '#cf1322', fontWeight: 600 }}>Monitoring: offline</span>
          )}
          {monStats && monDegraded && !monStatsFetchError && (
            <span style={{ fontSize: 12, color: '#d48806', fontWeight: 600 }}>Monitoring: partial</span>
          )}
        </div>
        <style>{`@keyframes glow { 0%,100% { box-shadow: 0 0 4px #52c41a } 50% { box-shadow: 0 0 12px #52c41a, 0 0 20px rgba(82,196,26,0.4) } }`}</style>
        <Pipeline alarmCount={alarms.count || 0} execCount={execs.count || 0} sources={sources} />
      </Card>

      {monStats && (
        <Card bordered={false} style={{ marginBottom: 16, borderRadius: 12 }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>Monitoring Coverage</div>
          <Row gutter={16}>
            <Col span={8}>
              <div
                style={{
                  background: '#f0f5ff',
                  borderRadius: 8,
                  padding: 16,
                  textAlign: 'center',
                  border: '1px solid #d6e4ff',
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    color: '#666',
                    textTransform: 'uppercase',
                    letterSpacing: 1,
                  }}
                >
                  Tier 1 — Thresholds
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#1890ff' }}>{monStats.tier1_rules}</div>
                <div style={{ fontSize: 12, color: '#999' }}>config-driven rules</div>
              </div>
            </Col>
            <Col span={8}>
              <div
                style={{
                  background: '#f6ffed',
                  borderRadius: 8,
                  padding: 16,
                  textAlign: 'center',
                  border: '1px solid #b7eb8f',
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    color: '#666',
                    textTransform: 'uppercase',
                    letterSpacing: 1,
                  }}
                >
                  Tier 2 — Anomaly Detection
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#52c41a' }}>
                  {(monStats.tier2_metrics ?? 0).toLocaleString()}
                </div>
                <div style={{ fontSize: 12, color: '#999' }}>metrics monitored (3σ)</div>
                <div
                  style={{ background: '#e6e6e6', borderRadius: 4, height: 6, marginTop: 6, overflow: 'hidden' }}
                >
                  <div
                    style={{
                      background: '#52c41a',
                      height: '100%',
                      width: `${monStats.tier2_pct ?? 0}%`,
                      borderRadius: 4,
                      transition: 'width 1s',
                    }}
                  />
                </div>
                <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                  {(monStats.tier2_pct ?? 0) < 50
                    ? 'warming up...'
                    : `${monStats.tier2_pct ?? 0}% baselined`}
                </div>
              </div>
            </Col>
            <Col span={8}>
              <div
                style={{
                  background: '#fff7e6',
                  borderRadius: 8,
                  padding: 16,
                  textAlign: 'center',
                  border: '1px solid #ffd591',
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    color: '#666',
                    textTransform: 'uppercase',
                    letterSpacing: 1,
                  }}
                >
                  Tier 3 — AI Classification
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#fa8c16' }}>Bedrock</div>
                <div style={{ fontSize: 12, color: '#999' }}>Claude Haiku on-demand</div>
                <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
                  max 1x/{(monStats.tier3_cooldown ?? 300) / 60}min
                </div>
              </div>
            </Col>
          </Row>
          <div style={{ textAlign: 'center', marginTop: 8, fontSize: 12, color: '#999' }}>
            {(monStats.tier2_metrics ?? 0).toLocaleString()} metrics · 4 layers · {monStats.alarm_definitions ?? 0}{' '}
            alarm definitions · guardrails: {Object.values(sources).filter(Boolean).length}/
            {Math.max(1, Object.keys(sources).length)} sources live
          </div>
        </Card>
      )}

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col flex="1 1 140px" style={{ minWidth: 140 }}>
          <Card bordered={false}>
            <Statistic title="Nodes" value={s.k8s_node_count || 0} prefix={<ClusterOutlined />} />
          </Card>
        </Col>
        <Col flex="1 1 140px" style={{ minWidth: 140 }}>
          <Card bordered={false}>
            <Statistic title="NF pods" value={s.nf_count || 0} prefix={<ApiOutlined />} />
          </Card>
        </Col>
        <Col flex="1 1 140px" style={{ minWidth: 140 }}>
          <Card bordered={false}>
            <Statistic
              title="Active alarms"
              value={alarms.count || 0}
              prefix={<AlertOutlined />}
              valueStyle={alarms.count > 0 ? { color: '#cf1322' } : {}}
            />
          </Card>
        </Col>
        <Col flex="1 1 140px" style={{ minWidth: 140 }}>
          <Card bordered={false}>
            <Statistic title="SOPs executed" value={execs.count || 0} prefix={<CheckCircleOutlined />} />
          </Card>
        </Col>
        <Col flex="1 1 140px" style={{ minWidth: 140 }}>
          <Card bordered={false}>
            <Statistic
              title="System status"
              value={systemStatus.text}
              prefix={systemStatus.icon}
              valueStyle={{ color: systemStatus.color }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title="Infrastructure nodes" bordered={false}>
            <Table
              dataSource={k8sNodes}
              rowKey="name"
              size="small"
              pagination={false}
              columns={[
                {
                  title: 'Name',
                  dataIndex: 'friendly',
                  render: (t, r) => (
                    <span style={{ position: 'relative', paddingRight: 10 }}>
                      {t} {r.role === 'edge' && <StatusDot live />}
                    </span>
                  ),
                },
                { title: 'IP', dataIndex: 'ip' },
                {
                  title: 'NFs (pods)',
                  dataIndex: 'nf_pod_count',
                  width: 100,
                  render: (v) => (typeof v === 'number' ? v : 0),
                },
                {
                  title: 'Role',
                  dataIndex: 'role',
                  render: (r) => <Tag color={r === 'edge' ? 'orange' : 'blue'}>{r}</Tag>,
                },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="Recent activity" bordered={false}>
            <Row gutter={[16, 16]}>
              <Col span={24} md={12}>
                <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 8, color: '#434343' }}>Alarms</div>
                {recentAlarms.length > 0 ? (
                  recentAlarms.map((a, i) => (
                    <div key={`a-${a.name}-${a.timestamp}-${i}`} style={{ padding: '6px 0', borderBottom: '1px solid #f0f0f0' }}>
                      <Tag color={a.severity === 'critical' ? 'red' : 'orange'}>{a.severity}</Tag>
                      <b>{a.name}</b>
                      <span style={{ float: 'right', color: '#999', fontSize: 12 }}>
                        {a.timestamp ? new Date(a.timestamp).toLocaleTimeString() : ''}
                      </span>
                    </div>
                  ))
                ) : (
                  <div style={{ color: '#999', fontSize: 13, padding: '4px 0' }}>No recent alarms</div>
                )}
              </Col>
              <Col span={24} md={12}>
                <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 8, color: '#434343' }}>SOP executions</div>
                {recentExecs.length > 0 ? (
                  recentExecs.map((e, i) => (
                    <div key={`e-${e.sop || ''}-${e.timestamp || i}`} style={{ padding: '6px 0', borderBottom: '1px solid #f0f0f0' }}>
                      <Tag color={e.result === 'success' || e.result === 'completed' ? 'green' : 'red'}>
                        {e.result || 'pending'}
                      </Tag>
                      <b>{(e.sop || '').split('/').pop()?.replace('.md', '') || e.alarm}</b>
                      <span style={{ float: 'right', color: '#999', fontSize: 12 }}>
                        {e.duration_seconds ? `${e.duration_seconds}s` : ''}
                      </span>
                    </div>
                  ))
                ) : (
                  <div style={{ color: '#999', fontSize: 13, padding: '4px 0' }}>No recent SOP runs</div>
                )}
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Dashboard
