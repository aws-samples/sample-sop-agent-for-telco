import { useMemo } from 'react'

// The path of the latest incident through the Network Assurance Agent and, after
// your approval, the Network Change Agent. Each stage is done, current, skipped
// or not reached; the state comes from the activity feed (see incidentStages).
const STAGES = [
  { key: 'detect', label: 'Detect', sub: 'Alertmanager alert', color: '#f5222d', icon: '/aws-icons/cloudwatch.svg' },
  { key: 'correlate', label: 'Correlate', sub: 'cause or symptom', color: '#722ed1', icon: '/aws-icons/sagemaker.svg' },
  { key: 'resolve', label: 'Resolve SOP', sub: 'reviewed or generated', color: '#1890ff', icon: '/aws-icons/inspector.svg' },
  { key: 'enrich', label: 'Enrich', sub: 'generated SOPs only', color: '#fa8c16', icon: '/aws-icons/bedrock.svg' },
  { key: 'approve', label: 'Approve', sub: 'you, in Decisions', color: '#13c2c2', icon: '/aws-icons/shield.svg' },
  { key: 'execute', label: 'Execute', sub: 'Network Change Agent', color: '#52c41a', icon: '/aws-icons/eks.svg' },
  { key: 'clear', label: 'Clear', sub: 'alert resolved', color: '#52c41a', icon: '/aws-icons/cloudwatch.svg' },
]

// Walk the feed from the latest "detect" of an alarm that was raised as a root
// cause (not suppressed) and mark which stages that incident reached.
export const incidentStages = (activity = []) => {
  const events = [...activity]
  let start = -1
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].stage === 'detect') {
      const name = (events[i].message || '').split(' ')[0]
      const suppressed = events.slice(i + 1).some(e => e.stage === 'correlate' && (e.message || '').startsWith(`${name}: symptom`))
      if (!suppressed) { start = i; break }
    }
  }
  if (start < 0) return { alarm: null, state: {} }
  const alarm = (events[start].message || '').split(' ')[0]
  const after = events.slice(start)
  const has = (pred) => after.some(pred)
  const state = { detect: 'done' }
  if (has(e => e.stage === 'correlate' && (e.message || '').startsWith(alarm))) state.correlate = 'done'
  if (has(e => e.stage === 'resolve')) state.resolve = 'done'
  const resolve = after.find(e => e.stage === 'resolve')
  const generated = resolve && /generat|\/tmp\//.test(resolve.message || '')
  if (has(e => e.stage === 'enrich')) state.enrich = 'done'
  else if (state.resolve && !generated) state.enrich = 'skipped'
  if (has(e => e.stage === 'execute' && /approved/i.test(e.message || ''))) state.approve = 'done'
  if (has(e => e.stage === 'execute' && /Completed/.test(e.message || ''))) state.execute = 'done'
  else if (has(e => e.stage === 'execute' && /failed|Failed/.test(e.message || ''))) state.execute = 'failed'
  else if (state.approve) state.execute = 'current'
  if (has(e => e.stage === 'clear' && (e.message || '').startsWith(alarm))) state.clear = 'done'
  // The first stage not yet done (and not skipped) is the current one.
  if (!Object.values(state).includes('current') && !state.clear) {
    const next = STAGES.find(s => !state[s.key])
    if (next) state[next.key] = 'current'
  }
  return { alarm, state }
}

const RemediationPipeline = ({ activity = [] }) => {
  const { alarm, state } = useMemo(() => incidentStages(activity), [activity])

  return (
    <div>
      <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 4 }}>
        {alarm ? <>Latest incident: <b style={{ color: '#434343' }}>{alarm}</b></> : 'No incident yet'}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: '12px 8px' }}>
        {STAGES.map((stage, i) => {
          const st = state[stage.key]
          const isActive = st === 'current'
          const isDone = st === 'done'
          const isSkipped = st === 'skipped'
          const isFailed = st === 'failed'
          const accent = isFailed ? '#ff4d4f' : isActive ? stage.color : isDone ? '#52c41a' : '#d9d9d9'
          const bg = isActive ? `${stage.color}10` : isDone ? '#f6ffed' : '#fafafa'
          return (
            <div key={stage.key} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
              <div
                data-testid={`stage-${stage.key}`}
                data-state={st || 'none'}
                style={{
                  background: bg, border: `2px ${isSkipped ? 'dashed' : 'solid'} ${accent}`, borderRadius: 10,
                  padding: '10px 8px', textAlign: 'center', minWidth: 90, position: 'relative',
                  boxShadow: isActive ? `0 0 12px ${stage.color}40` : 'none',
                }}
              >
                <img src={stage.icon} alt={stage.key} style={{ width: 24, height: 24, opacity: isActive || isDone ? 1 : 0.4 }} />
                <div style={{ fontWeight: 700, fontSize: 11, color: isFailed ? '#ff4d4f' : isActive ? stage.color : isDone ? '#52c41a' : '#8c8c8c' }}>
                  {stage.label}
                </div>
                <div style={{ fontSize: 9, color: '#999' }}>{isSkipped ? 'skipped: reviewed SOP' : stage.sub}</div>
              </div>
              {i < STAGES.length - 1 && (
                <div style={{ flex: 1, height: 2, minWidth: 12, background: isDone ? '#52c41a' : '#e8e8e8' }} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default RemediationPipeline
