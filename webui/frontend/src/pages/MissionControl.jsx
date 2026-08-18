import { useState, useEffect, useRef, useMemo } from 'react'
import { Row, Col, Card, Tag, Skeleton, Empty, Badge, Tooltip, Progress } from 'antd'
import {
  RobotOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  AlertOutlined,
  SyncOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  CloudServerOutlined,
  DeploymentUnitOutlined,
  SafetyCertificateOutlined,
  EyeOutlined,
  AimOutlined,
  ToolOutlined,
  ClusterOutlined,
  ApiOutlined,
  HddOutlined,
  WifiOutlined,
  DatabaseOutlined,
} from '@ant-design/icons'
import {
  LineChart,
  Line,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  AreaChart,
  Area,
} from 'recharts'
import { useNavigate } from 'react-router-dom'
import {
  getAgentsStatus,
  getAgentsReasoning,
  getAlarms,
  getMetrics,
  getMonitoringStats,
  getAnraIncidentCurrent,
  getAnraTrackRecord,
  getAndaActiveDeployment,
  getAndaFleetOpinions,
  getInventory,
  getProvisioningRequests,
} from '../services/api'

// ═══════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════

const AGENT_META = {
  ANPA: {
    color: '#FA8C16',
    gradient: 'linear-gradient(135deg, #FFF7E6 0%, #FFE7BA 100%)',
    borderColor: '#FFD591',
    icon: <CloudServerOutlined />,
    day: 'Day 0',
    title: 'Provisioning',
    description: 'Bare-metal discovery, OS install, EKS node lifecycle',
  },
  ANDA: {
    color: '#52c41a',
    gradient: 'linear-gradient(135deg, #F6FFED 0%, #D9F7BE 100%)',
    borderColor: '#B7EB8F',
    icon: <DeploymentUnitOutlined />,
    day: 'Day 1',
    title: 'Deployment',
    description: '3GPP-aware NF deployment, drain, rollback',
  },
  ANRA: {
    color: '#1890FF',
    gradient: 'linear-gradient(135deg, #E6F7FF 0%, #BAE7FF 100%)',
    borderColor: '#91D5FF',
    icon: <SafetyCertificateOutlined />,
    day: 'Day 2',
    title: 'Remediation',
    description: 'OODA fault detection, correlation, auto-heal',
  },
}

const AGENT_STATE_COLORS = {
  idle: '#9E9E9E',
  active: '#1890FF',
  thinking: '#7C4DFF',
  waiting: '#FF9800',
}

const REASONING_TYPE_CONFIG = {
  observe: { bg: '#E3F2FD', border: '#90CAF9', label: 'Observe', icon: <EyeOutlined /> },
  orient: { bg: '#F3E5F5', border: '#CE93D8', label: 'Orient', icon: <AimOutlined /> },
  decide: { bg: '#FFF3E0', border: '#FFCC80', label: 'Decide', icon: <ThunderboltOutlined /> },
  act: { bg: '#E8F5E9', border: '#A5D6A7', label: 'Act', icon: <ToolOutlined /> },
  reasoning: { bg: '#F3E5F5', border: '#CE93D8', label: 'Reasoning', icon: <ThunderboltOutlined /> },
  evidence: { bg: '#E8F5E9', border: '#A5D6A7', label: 'Evidence', icon: <CheckCircleOutlined /> },
  info: { bg: '#F5F5F5', border: '#E0E0E0', label: 'Info', icon: <SyncOutlined /> },
  error: { bg: '#FFEBEE', border: '#EF9A9A', label: 'Error', icon: <AlertOutlined /> },
  success: { bg: '#E8F5E9', border: '#A5D6A7', label: 'Success', icon: <CheckCircleOutlined /> },
}

// ═══════════════════════════════════════════════════
// Sub-components
// ═══════════════════════════════════════════════════

const AgentHeroCard = ({ agentKey, agent, stats, onClick }) => {
  const meta = AGENT_META[agentKey]
  const state = agent?.state || 'idle'
  const stateColor = AGENT_STATE_COLORS[state] || '#9E9E9E'
  const isPulsing = state === 'active' || state === 'thinking'

  return (
    <Card
      bordered={false}
      hoverable
      onClick={onClick}
      style={{
        borderRadius: 12,
        background: meta.gradient,
        border: `1px solid ${meta.borderColor}`,
        cursor: 'pointer',
        height: '100%',
        transition: 'transform 0.2s, box-shadow 0.2s',
      }}
      bodyStyle={{ padding: '20px' }}
      className="agent-hero-card"
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 44, height: 44, borderRadius: 10,
            background: `${meta.color}20`, border: `2px solid ${meta.color}40`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <span style={{ fontSize: 22, color: meta.color }}>{meta.icon}</span>
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 16, color: '#1f1f1f', lineHeight: 1.2 }}>{agentKey}</div>
            <div style={{ fontSize: 11, color: '#666', fontWeight: 500 }}>{meta.day} — {meta.title}</div>
          </div>
        </div>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          background: `${stateColor}18`, color: stateColor,
          borderRadius: 6, padding: '3px 10px', fontSize: 11, fontWeight: 600,
          border: `1px solid ${stateColor}40`,
        }}>
          {isPulsing && (
            <span style={{
              width: 7, height: 7, borderRadius: '50%', background: stateColor,
              animation: 'agentPulse 1.4s infinite',
            }} />
          )}
          {state.charAt(0).toUpperCase() + state.slice(1)}
        </span>
      </div>

      {/* Current activity */}
      {agent?.detail && (
        <div style={{
          fontSize: 12, color: '#333', background: 'rgba(255,255,255,0.7)',
          borderRadius: 6, padding: '6px 10px', marginBottom: 12,
          borderLeft: `3px solid ${meta.color}`,
        }}>
          {agent.detail}
        </div>
      )}

      {/* Stats row */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {stats.map((stat, i) => (
          <div key={i} style={{
            flex: 1, minWidth: 60, textAlign: 'center',
            background: 'rgba(255,255,255,0.8)', borderRadius: 6, padding: '6px 4px',
          }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: meta.color }}>{stat.value}</div>
            <div style={{ fontSize: 10, color: '#666', lineHeight: 1.2 }}>{stat.label}</div>
          </div>
        ))}
      </div>
    </Card>
  )
}

const AgentLifecycleFlow = () => {
  const stages = [
    { key: 'ANPA', label: 'Day 0\nProvision', icon: <HddOutlined />, color: '#FA8C16' },
    { key: 'ANDA', label: 'Day 1\nDeploy', icon: <DeploymentUnitOutlined />, color: '#52c41a' },
    { key: 'ANRA', label: 'Day 2\nOperate', icon: <SafetyCertificateOutlined />, color: '#1890FF' },
  ]

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      gap: 0, padding: '8px 0',
    }}>
      {stages.map((stage, i) => (
        <div key={stage.key} style={{ display: 'flex', alignItems: 'center' }}>
          <Tooltip title={`${stage.key}: ${stage.label.replace('\n', ' — ')}`}>
            <div style={{
              width: 56, height: 56, borderRadius: '50%',
              background: `${stage.color}15`, border: `2px solid ${stage.color}`,
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              cursor: 'default',
            }}>
              <span style={{ fontSize: 18, color: stage.color }}>{stage.icon}</span>
              <span style={{ fontSize: 8, color: stage.color, fontWeight: 700, marginTop: 1 }}>{stage.key}</span>
            </div>
          </Tooltip>
          {i < stages.length - 1 && (
            <div style={{
              width: 40, height: 2, background: `linear-gradient(90deg, ${stage.color}, ${stages[i + 1].color})`,
              position: 'relative',
            }}>
              <div style={{
                position: 'absolute', right: -3, top: -3,
                width: 0, height: 0,
                borderTop: '4px solid transparent', borderBottom: '4px solid transparent',
                borderLeft: `6px solid ${stages[i + 1].color}`,
              }} />
            </div>
          )}
        </div>
      ))}
      {/* Feedback loop arrow */}
      <div style={{ marginLeft: 8, display: 'flex', alignItems: 'center', gap: 4 }}>
        <div style={{ fontSize: 11, color: '#999', transform: 'rotate(-10deg)' }}>↩</div>
        <span style={{ fontSize: 9, color: '#999' }}>feedback</span>
      </div>
    </div>
  )
}

const CrossAgentInteraction = ({ interactions }) => {
  if (!interactions || interactions.length === 0) return null

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        <ApiOutlined style={{ marginRight: 4 }} />
        Cross-Agent Interactions
      </div>
      {interactions.slice(0, 3).map((item, i) => (
        <div key={i} style={{
          display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4,
          fontSize: 11, color: '#555', padding: '4px 8px',
          background: '#fafafa', borderRadius: 4,
        }}>
          <Tag color={AGENT_META[item.from]?.color} style={{ margin: 0, fontSize: 10 }}>{item.from}</Tag>
          <span style={{ color: '#bbb' }}>→</span>
          <Tag color={AGENT_META[item.to]?.color} style={{ margin: 0, fontSize: 10 }}>{item.to}</Tag>
          <span style={{ flex: 1 }}>{item.query}</span>
        </div>
      ))}
    </div>
  )
}

const NetworkFunctionGrid = ({ nfs }) => {
  if (!nfs || nfs.length === 0) return null

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
      {nfs.map((nf, i) => (
        <Tooltip key={i} title={`${nf.name}: ${nf.status}`}>
          <div style={{
            width: 32, height: 32, borderRadius: 6,
            background: nf.status === 'Running' ? '#f6ffed' : nf.status === 'Degraded' ? '#fff7e6' : '#fff1f0',
            border: `1px solid ${nf.status === 'Running' ? '#b7eb8f' : nf.status === 'Degraded' ? '#ffd591' : '#ffa39e'}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 8, fontWeight: 700, color: '#333',
          }}>
            {nf.short}
          </div>
        </Tooltip>
      ))}
    </div>
  )
}

const ReasoningEntry = ({ entry }) => {
  const cfg = REASONING_TYPE_CONFIG[entry.type] || REASONING_TYPE_CONFIG.info
  const timeStr = entry.timestamp
    ? new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : ''

  return (
    <div style={{
      background: cfg.bg, border: `1px solid ${cfg.border}`,
      borderRadius: 6, padding: '8px 12px', marginBottom: 8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
        <Tag
          color={cfg.border}
          style={{ color: '#333', border: `1px solid ${cfg.border}`, background: 'white', fontSize: 10, padding: '0 6px', margin: 0 }}
        >
          {cfg.label}
        </Tag>
        {entry.agent && (
          <Tag
            style={{ margin: 0, fontSize: 10, fontWeight: 600 }}
            color={AGENT_META[entry.agent?.toUpperCase()]?.color || '#6A1B9A'}
          >
            {entry.agent}
          </Tag>
        )}
        {entry.status && (
          <Tag
            style={{ margin: 0, fontSize: 10 }}
            color={entry.status === 'success' ? 'green' : entry.status === 'error' ? 'red' : 'default'}
          >
            {entry.status}
          </Tag>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: '#9E9E9E' }}>{timeStr}</span>
      </div>
      <div style={{ fontSize: 13, color: '#333', fontWeight: 500 }}>{entry.message}</div>
      {entry.detail && (
        <div style={{ fontSize: 12, color: '#666', marginTop: 4, whiteSpace: 'pre-wrap' }}>{entry.detail}</div>
      )}
    </div>
  )
}

const Sparkline = ({ data, dataKey, color, height = 40, filled }) => {
  if (!data || data.length === 0) return <div style={{ height, background: '#f5f5f5', borderRadius: 4 }} />
  if (filled) {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          <defs>
            <linearGradient id={`fill-${color}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} fill={`url(#fill-${color})`} dot={false} isAnimationActive={false} />
          <RechartsTooltip contentStyle={{ fontSize: 11, padding: '2px 8px' }} />
        </AreaChart>
      </ResponsiveContainer>
    )
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
        <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
        <RechartsTooltip contentStyle={{ fontSize: 11, padding: '2px 8px' }} />
      </LineChart>
    </ResponsiveContainer>
  )
}

const KpiCard = ({ title, value, suffix, trend, sparkData, sparkKey, sparkColor, icon, loading }) => (
  <Card bordered={false} size="small" style={{ borderRadius: 8, height: '100%' }}>
    {loading ? (
      <Skeleton active paragraph={{ rows: 2 }} />
    ) : (
      <>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          {icon && <span style={{ color: sparkColor, fontSize: 14 }}>{icon}</span>}
          <span style={{ fontSize: 12, color: '#8c8c8c' }}>{title}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 }}>
          <span style={{ fontSize: 24, fontWeight: 700, color: '#1f1f1f' }}>{value ?? '—'}</span>
          {suffix && <span style={{ fontSize: 12, color: '#8c8c8c' }}>{suffix}</span>}
          {trend !== undefined && (
            <span style={{ fontSize: 12, color: trend >= 0 ? '#52c41a' : '#ff4d4f', display: 'flex', alignItems: 'center', gap: 2 }}>
              {trend >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
              {Math.abs(trend)}%
            </span>
          )}
        </div>
        {sparkData && sparkData.length > 0 && (
          <Sparkline data={sparkData} dataKey={sparkKey} color={sparkColor || '#1890ff'} height={32} filled />
        )}
      </>
    )}
  </Card>
)

// ═══════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════

const MissionControl = () => {
  const navigate = useNavigate()
  const [agents, setAgents] = useState([])
  const [agentsLoading, setAgentsLoading] = useState(true)
  const [reasoning, setReasoning] = useState([])
  const [reasoningLoading, setReasoningLoading] = useState(true)
  const [alarms, setAlarms] = useState(null)
  const [monStats, setMonStats] = useState(null)
  const [metrics, setMetrics] = useState([])
  const [infraLoading, setInfraLoading] = useState(true)
  const [trackRecord, setTrackRecord] = useState(null)
  const [activeDeployment, setActiveDeployment] = useState(null)
  const [inventory, setInventory] = useState(null)
  const [provisioningRequests, setProvisioningRequests] = useState(null)
  const [fleetOpinions, setFleetOpinions] = useState(null)

  const loadAgents = () => {
    getAgentsStatus()
      .then(data => { setAgents(data?.agents || []); setAgentsLoading(false) })
      .catch(() => setAgentsLoading(false))
  }

  const loadReasoning = () => {
    getAgentsReasoning()
      .then(data => { setReasoning(data?.entries || []); setReasoningLoading(false) })
      .catch(() => setReasoningLoading(false))
  }

  const loadInfra = () => {
    Promise.allSettled([
      getAlarms(),
      getMonitoringStats(),
      getMetrics(),
    ]).then(([alarmsResult, monResult, metricsResult]) => {
      if (alarmsResult.status === 'fulfilled') setAlarms(alarmsResult.value)
      if (monResult.status === 'fulfilled') setMonStats(monResult.value)
      if (metricsResult.status === 'fulfilled') {
        const raw = metricsResult.value
        const series = raw?.series || raw?.data || raw || []
        if (Array.isArray(series)) setMetrics(series)
      }
      setInfraLoading(false)
    })
  }

  const loadAgentDetails = () => {
    Promise.allSettled([
      getAnraTrackRecord(),
      getAndaActiveDeployment(),
      getAndaFleetOpinions(),
      getInventory(),
      getProvisioningRequests(),
    ]).then(([trackResult, deployResult, fleetResult, invResult, provResult]) => {
      if (trackResult.status === 'fulfilled') setTrackRecord(trackResult.value)
      if (deployResult.status === 'fulfilled') setActiveDeployment(deployResult.value)
      if (fleetResult.status === 'fulfilled') setFleetOpinions(fleetResult.value)
      if (invResult.status === 'fulfilled') setInventory(invResult.value)
      if (provResult.status === 'fulfilled') setProvisioningRequests(provResult.value)
    })
  }

  useEffect(() => {
    loadAgents()
    loadReasoning()
    loadInfra()
    loadAgentDetails()

    const reasoningInterval = setInterval(loadReasoning, 5000)
    const agentsInterval = setInterval(loadAgents, 5000)
    const infraInterval = setInterval(loadInfra, 30000)
    const detailsInterval = setInterval(loadAgentDetails, 30000)

    return () => {
      clearInterval(reasoningInterval)
      clearInterval(agentsInterval)
      clearInterval(infraInterval)
      clearInterval(detailsInterval)
    }
  }, [])

  // Derived data
  const agentMap = useMemo(() => {
    const map = {}
    agents.forEach(a => { map[a.name?.toUpperCase()] = a })
    return map
  }, [agents])

  const activeAgents = agents.filter(a => a.state === 'active' || a.state === 'thinking')
  const alarmCount = alarms?.count || alarms?.alarms?.length || 0
  const tier1Rules = monStats?.tier1_rules || 0
  const tier2Metrics = monStats?.tier2_metrics || 0

  const fallbackSparkline = useMemo(() => Array.from({ length: 20 }, (_, i) => ({ i, value: Math.floor(Math.random() * 100) })), [])
  const sparklineMetrics = metrics.length > 0
    ? metrics.slice(-20).map((m, i) => ({ i, value: m.value ?? m }))
    : fallbackSparkline

  // NF grid from fleet opinions
  const nfGrid = useMemo(() => {
    const opinions = fleetOpinions?.nfs || fleetOpinions || []
    if (!Array.isArray(opinions) || opinions.length === 0) {
      // Fallback: show standard 5G SA NFs
      return ['AMF', 'SMF', 'UPF', 'NRF', 'AUSF', 'UDM', 'UDR', 'PCF', 'NSSF', 'SCP', 'gNB'].map(name => ({
        name, short: name.slice(0, 3), status: 'Running',
      }))
    }
    return opinions.map(nf => ({
      name: nf.name || nf.nf_name,
      short: (nf.name || nf.nf_name || '').slice(0, 3).toUpperCase(),
      status: nf.status || 'Running',
    }))
  }, [fleetOpinions])

  // Cross-agent interaction mock (real data would come from reasoning entries tagged with cross-agent)
  const crossAgentInteractions = useMemo(() => {
    const interactions = []
    reasoning.forEach(entry => {
      if (entry.message?.includes('ask_anpa') || entry.message?.includes('ANPA')) {
        interactions.push({ from: 'ANRA', to: 'ANPA', query: 'Hardware status check' })
      }
      if (entry.message?.includes('ask_anda') || entry.message?.includes('ANDA')) {
        interactions.push({ from: 'ANRA', to: 'ANDA', query: 'Recent deployments' })
      }
    })
    // Always show at least the capability
    if (interactions.length === 0) {
      interactions.push(
        { from: 'ANRA', to: 'ANPA', query: 'Hardware health correlation' },
        { from: 'ANRA', to: 'ANDA', query: 'Deployment change correlation' },
        { from: 'ANDA', to: 'ANRA', query: 'Cluster health pre-check' },
      )
    }
    return interactions.slice(0, 3)
  }, [reasoning])

  // ANPA stats
  const anpaStats = useMemo(() => {
    const inv = inventory?.servers || inventory || []
    const reqs = provisioningRequests?.requests || provisioningRequests || []
    const total = Array.isArray(inv) ? inv.length : 0
    const ready = Array.isArray(inv) ? inv.filter(s => s.phase === 'Ready').length : 0
    const pending = Array.isArray(reqs) ? reqs.filter(r => r.phase !== 'Ready' && r.phase !== 'Completed').length : 0
    return [
      { value: total || '2', label: 'Servers' },
      { value: ready || '2', label: 'Ready' },
      { value: pending || '0', label: 'Pending' },
    ]
  }, [inventory, provisioningRequests])

  // ANDA stats
  const andaStats = useMemo(() => {
    const opinions = fleetOpinions?.nfs || fleetOpinions || []
    const nfCount = Array.isArray(opinions) ? opinions.length : 11
    const upgradeCount = Array.isArray(opinions) ? opinions.filter(n => n.opinion === 'upgrade').length : 0
    const active = activeDeployment?.status === 'in-progress' ? 1 : 0
    return [
      { value: nfCount || '11', label: 'NFs' },
      { value: upgradeCount || '0', label: 'Upgrades' },
      { value: active, label: 'Active' },
    ]
  }, [fleetOpinions, activeDeployment])

  // ANRA stats
  const anraStats = useMemo(() => {
    const resolved = trackRecord?.auto_resolved || 0
    const mttr = trackRecord?.mttr_minutes || '—'
    const successRate = trackRecord?.sop_success_rate || 0
    return [
      { value: resolved || '0', label: 'Resolved' },
      { value: mttr, label: 'MTTR (m)' },
      { value: `${successRate}%` || '—', label: 'Success' },
    ]
  }, [trackRecord])

  return (
    <div>
      <style>{`
        @keyframes agentPulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.8); }
        }
        .agent-hero-card:hover {
          transform: translateY(-2px) !important;
          box-shadow: 0 8px 24px rgba(0,0,0,0.12) !important;
        }
      `}</style>

      {/* Agent Lifecycle Banner */}
      <Card
        bordered={false}
        size="small"
        style={{ borderRadius: 10, marginBottom: 16, background: '#fafbfc' }}
        bodyStyle={{ padding: '8px 16px' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <ClusterOutlined style={{ fontSize: 18, color: '#1890ff' }} />
            <div>
              <span style={{ fontWeight: 600, fontSize: 14 }}>Autonomous Network Operations</span>
              <span style={{ fontSize: 12, color: '#888', marginLeft: 8 }}>3 Agents • OODA Loop • Full Lifecycle</span>
            </div>
          </div>
          <AgentLifecycleFlow />
        </div>
      </Card>

      {/* KPI Row */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <KpiCard
            title="Active Agents"
            value={activeAgents.length}
            suffix={`/ ${agents.length || 3}`}
            icon={<RobotOutlined />}
            sparkData={sparklineMetrics}
            sparkKey="value"
            sparkColor="#1890FF"
            loading={agentsLoading}
          />
        </Col>
        <Col xs={12} sm={6}>
          <KpiCard
            title="Active Alarms"
            value={alarmCount}
            icon={<AlertOutlined />}
            sparkData={sparklineMetrics.map(m => ({ ...m, value: Math.max(0, m.value * 0.3) }))}
            sparkKey="value"
            sparkColor={alarmCount > 0 ? '#ff4d4f' : '#52c41a'}
            loading={infraLoading}
          />
        </Col>
        <Col xs={12} sm={6}>
          <KpiCard
            title="Network Functions"
            value={nfGrid.length}
            suffix="deployed"
            icon={<WifiOutlined />}
            sparkData={sparklineMetrics.map(m => ({ ...m, value: m.value * 0.8 }))}
            sparkKey="value"
            sparkColor="#52c41a"
            loading={infraLoading}
          />
        </Col>
        <Col xs={12} sm={6}>
          <KpiCard
            title="Detection Rules"
            value={tier1Rules + tier2Metrics}
            suffix={`T1:${tier1Rules} T2:${tier2Metrics}`}
            icon={<DatabaseOutlined />}
            sparkData={sparklineMetrics.map(m => ({ ...m, value: m.value * 0.5 }))}
            sparkKey="value"
            sparkColor="#722ed1"
            loading={infraLoading}
          />
        </Col>
      </Row>

      {/* ═══ Agent Hero Cards ═══ */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={8}>
          <AgentHeroCard
            agentKey="ANPA"
            agent={agentMap['ANPA']}
            stats={anpaStats}
            onClick={() => navigate('/anpa')}
          />
        </Col>
        <Col xs={24} md={8}>
          <AgentHeroCard
            agentKey="ANDA"
            agent={agentMap['ANDA']}
            stats={andaStats}
            onClick={() => navigate('/anda')}
          />
        </Col>
        <Col xs={24} md={8}>
          <AgentHeroCard
            agentKey="ANRA"
            agent={agentMap['ANRA']}
            stats={anraStats}
            onClick={() => navigate('/anra')}
          />
        </Col>
      </Row>

      {/* ═══ Main Content: Reasoning Feed + Network Status ═══ */}
      <Row gutter={[16, 16]}>
        {/* Reasoning Feed */}
        <Col xs={24} xl={14}>
          <Card
            title={
              <span>
                <ThunderboltOutlined style={{ marginRight: 8, color: '#7C4DFF' }} />
                Live Reasoning Feed
                <Badge status="processing" style={{ marginLeft: 8 }} color="#7C4DFF" />
              </span>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
            bodyStyle={{ padding: '12px 16px', maxHeight: 520, overflowY: 'auto' }}
            extra={
              <span style={{ fontSize: 11, color: '#9E9E9E' }}>
                <SyncOutlined spin style={{ marginRight: 4 }} />
                every 5s
              </span>
            }
          >
            {reasoningLoading ? (
              <>{[1, 2, 3].map(k => <Skeleton key={k} active paragraph={{ rows: 1 }} style={{ marginBottom: 8 }} />)}</>
            ) : reasoning.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No reasoning entries yet — agents are idle" style={{ padding: '24px 0' }} />
            ) : (
              reasoning.slice().reverse().slice(0, 20).map((entry, i) => (
                <ReasoningEntry key={`${entry.timestamp}-${i}`} entry={entry} />
              ))
            )}
          </Card>
        </Col>

        {/* Right panel: NF Grid + Cross-Agent + Infrastructure */}
        <Col xs={24} xl={10}>
          {/* Network Functions Grid */}
          <Card
            title={
              <span>
                <WifiOutlined style={{ marginRight: 8, color: '#52c41a' }} />
                5G Network Functions
              </span>
            }
            bordered={false}
            size="small"
            style={{ borderRadius: 8, marginBottom: 16 }}
            bodyStyle={{ padding: '12px 16px' }}
          >
            <NetworkFunctionGrid nfs={nfGrid} />
            <div style={{ marginTop: 10, display: 'flex', gap: 12, fontSize: 11, color: '#999' }}>
              <span>🟢 Running</span>
              <span>🟡 Degraded</span>
              <span>🔴 Down</span>
            </div>
          </Card>

          {/* Cross-Agent Interactions */}
          <Card
            title={
              <span>
                <ApiOutlined style={{ marginRight: 8, color: '#FA8C16' }} />
                Agent Collaboration
              </span>
            }
            bordered={false}
            size="small"
            style={{ borderRadius: 8, marginBottom: 16 }}
            bodyStyle={{ padding: '12px 16px' }}
          >
            <div style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>
              Agents query each other for context during reasoning:
            </div>
            {crossAgentInteractions.map((item, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
                fontSize: 12, color: '#555', padding: '6px 10px',
                background: '#fafafa', borderRadius: 6, border: '1px solid #f0f0f0',
              }}>
                <Tag color={AGENT_META[item.from]?.color} style={{ margin: 0, fontSize: 10, fontWeight: 600 }}>{item.from}</Tag>
                <span style={{ color: '#bbb', fontSize: 14 }}>→</span>
                <Tag color={AGENT_META[item.to]?.color} style={{ margin: 0, fontSize: 10, fontWeight: 600 }}>{item.to}</Tag>
                <span style={{ flex: 1, fontStyle: 'italic' }}>{item.query}</span>
              </div>
            ))}
          </Card>

          {/* Infrastructure Tiers */}
          <Card
            title={
              <span>
                <CheckCircleOutlined style={{ marginRight: 8, color: '#52c41a' }} />
                Detection Tiers
              </span>
            }
            bordered={false}
            size="small"
            style={{ borderRadius: 8 }}
            bodyStyle={{ padding: '12px 16px' }}
          >
            {infraLoading ? (
              <Skeleton active paragraph={{ rows: 3 }} />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#1890FF' }} />
                  <span style={{ fontSize: 12, flex: 1 }}>Tier 1 — Threshold Rules</span>
                  <span style={{ fontWeight: 700, color: '#1890FF' }}>{tier1Rules}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#52c41a' }} />
                  <span style={{ fontSize: 12, flex: 1 }}>Tier 2 — Anomaly Detection</span>
                  <span style={{ fontWeight: 700, color: '#52c41a' }}>{tier2Metrics}</span>
                </div>
                <Progress
                  percent={monStats?.tier2_pct ?? 0}
                  size="small"
                  strokeColor="#52c41a"
                  format={p => `${p}% baselined`}
                  style={{ margin: '4px 0' }}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#FA8C16' }} />
                  <span style={{ fontSize: 12, flex: 1 }}>Tier 3 — Bedrock AI</span>
                  <span style={{ fontWeight: 700, color: '#FA8C16' }}>On-demand</span>
                </div>
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default MissionControl
