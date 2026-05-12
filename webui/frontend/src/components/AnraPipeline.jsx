import { useState, useEffect } from 'react'

const ANIM = `
@keyframes flowRight { 0% { left: 0%; opacity: 0 } 20% { opacity: 1 } 80% { opacity: 1 } 100% { left: 100%; opacity: 0 } }
@keyframes glow { 0%,100% { box-shadow: 0 0 4px #52c41a } 50% { box-shadow: 0 0 12px #52c41a, 0 0 20px rgba(82,196,26,0.4) } }
`

const AWS = {
  radio: '/aws-icons/eks-hybrid.svg',
  core: '/aws-icons/eks.svg',
  server: '/aws-icons/outposts.svg',
  k8s: '/aws-icons/eks.svg',
  db: '/aws-icons/timestream.svg',
  chart: '/aws-icons/cloudwatch.svg',
  brain: '/aws-icons/sagemaker.svg',
  bot: '/aws-icons/bedrock.svg',
  wrench: '/aws-icons/ssm.svg',
  search: '/aws-icons/inspector.svg',
  check: '/aws-icons/shield.svg',
  target: '/aws-icons/shield.svg',
  refresh: '/aws-icons/cloudwatch.svg',
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

const Box = ({ label, sub, color, icon, active, live }) => (
  <div
    style={{
      background: color,
      border: `2px solid ${active ? '#1890ff' : '#d9d9d9'}`,
      borderRadius: 10,
      padding: '10px 14px',
      textAlign: 'center',
      minWidth: 90,
      position: 'relative',
      boxShadow: active ? '0 0 8px rgba(0,0,0,0.08)' : 'none',
    }}
  >
    {live !== undefined && <StatusDot live={live} />}
    <div style={{ marginBottom: 2 }}>
      {AWS[icon] ? (
        <img src={AWS[icon]} alt="" style={{ width: 28, height: 28 }} />
      ) : (
        <span style={{ fontSize: 20 }}>{icon}</span>
      )}
    </div>
    <div style={{ fontWeight: 700, fontSize: 11, color: '#232F3E' }}>{label}</div>
    {sub && <div style={{ fontSize: 10, color: '#666' }}>{sub}</div>}
  </div>
)

const Arrow = ({ color = '#1890ff', delay = 0, label }) => (
  <div
    style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minWidth: 50,
      position: 'relative',
    }}
  >
    <div
      style={{
        width: '100%',
        height: 2,
        background: '#e0e0e0',
        position: 'relative',
        overflow: 'hidden',
        borderRadius: 1,
      }}
    >
      <div
        style={{
          position: 'absolute',
          width: 10,
          height: 10,
          borderRadius: '50%',
          background: color,
          top: -4,
          animation: `flowRight 2s ${delay}s infinite ease-in-out`,
        }}
      />
    </div>
    {label && <div style={{ fontSize: 9, color: '#999', marginTop: 2 }}>{label}</div>}
  </div>
)

/** Four sources into InfluxDB; animated path dots (one Telegraf label for the bundle). */
const CollectSVG = ({ sources }) => {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setTick(p => (p + 1) % 200), 30)
    return () => clearInterval(t)
  }, [])

  const srcNodes = [
    { id: 'ran', label: '5G RAN', sub: 'WebSocket', color: '#ff9800', y: 22, live: sources.ran, icon: 'radio' },
    { id: 'core', label: '5G Core', sub: 'Prometheus', color: '#9c27b0', y: 66, live: sources.core, icon: 'core' },
    { id: 'hw', label: 'Hardware', sub: 'Redfish', color: '#e65100', y: 110, live: sources.hardware, icon: 'server' },
    { id: 'os', label: 'OS / K8s', sub: 'kubectl', color: '#43a047', y: 154, live: sources.os, icon: 'k8s' },
  ]
  const dbX = 230
  const dbY = 88

  return (
    <div>
      <div
        style={{ position: 'relative', width: 310, minWidth: 200, maxWidth: '100%', height: 185, margin: '0 auto' }}
        aria-label="Telemetry: sources to InfluxDB"
      >
        <svg
          viewBox="0 0 310 185"
          style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}
          aria-hidden
        >
          {srcNodes.map((n, i) => {
            const sx = 95
            const sy = n.y
            const fwd = ((tick + i * 40) % 200) / 200
            const mx = sx + (dbX - sx) * fwd
            const my = sy + (dbY - sy) * fwd
            return (
              <g key={n.id}>
                <line x1={sx} y1={sy} x2={dbX} y2={dbY} stroke={n.color} strokeWidth="1.5" opacity="0.25" />
                <circle cx={mx} cy={my} r="4" fill={n.color} opacity="0.9" />
              </g>
            )
          })}
        </svg>
        {srcNodes.map(n => (
          <div key={n.id} style={{ position: 'absolute', left: 0, top: n.y - 15, width: 90 }}>
            <div
              style={{
                background: '#fff',
                border: `2px solid ${n.live ? '#52c41a' : '#d9d9d9'}`,
                borderRadius: 8,
                padding: '4px 6px',
                textAlign: 'center',
                position: 'relative',
              }}
            >
              <div
                style={{
                  position: 'absolute',
                  top: 3,
                  right: 3,
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: n.live ? '#52c41a' : '#d9d9d9',
                  animation: n.live ? 'glow 2s infinite' : 'none',
                }}
              />
              {AWS[n.icon] && <img src={AWS[n.icon]} alt="" style={{ width: 20, height: 20 }} />}
              <div style={{ fontWeight: 700, fontSize: 9, color: '#232F3E' }}>{n.label}</div>
              <div style={{ fontSize: 8, color: '#999' }}>{n.sub}</div>
            </div>
          </div>
        ))}
        <div style={{ position: 'absolute', left: dbX - 45, top: dbY - 32, width: 90 }}>
          <div
            style={{
              background: '#e3f2fd',
              border: '2px solid #1890ff',
              borderRadius: 8,
              padding: '6px 8px',
              textAlign: 'center',
            }}
          >
            {AWS.db && <img src={AWS.db} alt="" style={{ width: 24, height: 24 }} />}
            <div style={{ fontWeight: 700, fontSize: 10, color: '#232F3E' }}>InfluxDB</div>
            <div style={{ fontSize: 8, color: '#666' }}>Time-Series</div>
          </div>
        </div>
      </div>
      <div
        style={{
          fontSize: 10,
          color: '#888',
          textAlign: 'center',
          marginTop: 4,
          maxWidth: 310,
        }}
      >
        Ingest path: <strong>Telegraf</strong> → InfluxDB (per-source collectors)
      </div>
    </div>
  )
}

export const Pipeline = ({ alarmCount, execCount, sources }) => (
  <div style={{ padding: '16px 0' }}>
    <style>{ANIM}</style>

    <div style={{ overflowX: 'auto', paddingBottom: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 12, minWidth: 720, flexWrap: 'nowrap' }}>
        <CollectSVG sources={sources} />

        <Arrow color="#2196f3" delay={0.5} label="poll 30s" />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <Box
            label="Threshold"
            sub="Known alarms"
            color={alarmCount > 0 ? '#ffebee' : '#e8f5e9'}
            icon="chart"
            active={alarmCount > 0}
          />
          <Box
            label="Anomaly"
            sub="Statistical 3σ"
            color={alarmCount > 0 ? '#fff3e0' : '#e8f5e9'}
            icon="chart"
            active={alarmCount > 0}
          />
        </div>

        <Arrow color="#9c27b0" delay={0.8} label="events" />
        <Box label="Correlate" sub="NetworkX RCA" color="#f3e5f5" icon="brain" active={alarmCount > 0} />
      </div>
    </div>

    <div
      style={{
        overflowX: 'auto',
        paddingBottom: 4,
      }}
    >
      <div
        style={{
          background: '#fafafa',
          borderRadius: 8,
          padding: '10px 12px',
          border: '1px dashed #d9d9d9',
          minWidth: 700,
        }}
      >
        <div style={{ fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 8 }}>
          Remediation Loop (Strands Agent + Bedrock)
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'nowrap' }}>
          <Box label="Resolve SOP" sub="match or generate" color="#fff8e1" icon="search" active={execCount > 0} />
          <Arrow color="#ff9800" delay={0} />
          <Box label="Bedrock" sub="Haiku → Sonnet" color="#fff8e1" icon="bot" active={execCount > 0} />
          <Arrow color="#f44336" delay={0.3} />
          <Box label="Execute" sub="kubectl + SSM" color="#fce4ec" icon="wrench" active={execCount > 0} />
          <Arrow color="#f44336" delay={0.6} />
          <Box label="Evaluate" sub="pass / fail?" color="#e8f5e9" icon="check" active={execCount > 0} />
          <Arrow color="#ff9800" delay={0.9} />
          <Box label="Correct" sub="escalate model" color="#fff3e0" icon="refresh" active={false} />
          <Arrow color="#4caf50" delay={1.2} />
          <Box label="Verify" sub="alarm cleared?" color="#e8f5e9" icon="target" active={false} />
        </div>
      </div>
    </div>
  </div>
)
