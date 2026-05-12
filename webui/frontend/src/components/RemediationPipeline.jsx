import { useMemo } from 'react'

const STAGES = [
  { key: 'collect', label: 'Collect', sub: '6 sources · 30s', color: '#8c8c8c', icon: '/aws-icons/cloudwatch.svg' },
  { key: 'detect', label: 'Detect', sub: '14 rules + 3σ', color: '#f5222d', icon: '/aws-icons/cloudwatch.svg' },
  { key: 'correlate', label: 'Correlate', sub: 'NetworkX · 4 layers', color: '#722ed1', icon: '/aws-icons/sagemaker.svg' },
  { key: 'resolve', label: 'Resolve', sub: '19 SOPs + generate', color: '#1890ff', icon: '/aws-icons/inspector.svg' },
  { key: 'enrich', label: 'Enrich', sub: 'Bedrock + env scan', color: '#fa8c16', icon: '/aws-icons/bedrock.svg' },
  { key: 'execute', label: 'Execute', sub: 'Strands agent', color: '#52c41a', icon: '/aws-icons/ssm.svg' },
]

const stageIndex = (key) => STAGES.findIndex(s => s.key === key)

const RemediationPipeline = ({ activeStage }) => {
  const activeIdx = useMemo(() => stageIndex(activeStage), [activeStage])

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: '16px 8px' }}>
      {STAGES.map((stage, i) => {
        const isActive = i === activeIdx
        const isDone = activeIdx >= 0 && i < activeIdx
        const dotColor = isActive ? stage.color : isDone ? '#52c41a' : '#d9d9d9'
        const borderColor = isActive ? stage.color : isDone ? '#52c41a' : '#e8e8e8'
        const bg = isActive ? `${stage.color}10` : isDone ? '#f6ffed' : '#fafafa'

        return (
          <div key={stage.key} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
            <div style={{
              background: bg, border: `2px solid ${borderColor}`, borderRadius: 10,
              padding: '10px 8px', textAlign: 'center', minWidth: 90, position: 'relative',
              transition: 'all 0.4s ease',
              boxShadow: isActive ? `0 0 12px ${stage.color}40` : 'none',
            }}>
              {/* Status dot */}
              <div style={{
                position: 'absolute', top: 6, right: 6, width: 8, height: 8, borderRadius: '50%',
                background: dotColor, transition: 'all 0.4s ease',
                boxShadow: isActive ? `0 0 8px ${stage.color}` : 'none',
                animation: isActive ? 'pipelinePulse 1.5s infinite' : 'none',
              }} />
              <img src={stage.icon} alt={stage.key} style={{ width: 24, height: 24, opacity: isActive || isDone ? 1 : 0.4, transition: 'opacity 0.4s' }} />
              <div style={{ fontWeight: 700, fontSize: 11, color: isActive ? stage.color : isDone ? '#52c41a' : '#8c8c8c', transition: 'color 0.4s' }}>{stage.label}</div>
              <div style={{ fontSize: 9, color: '#999' }}>{stage.sub}</div>
            </div>
            {/* Arrow connector */}
            {i < STAGES.length - 1 && (
              <div style={{ flex: 1, height: 2, minWidth: 20, position: 'relative', overflow: 'hidden' }}>
                <div style={{ width: '100%', height: 2, background: isDone ? '#52c41a' : '#e8e8e8', transition: 'background 0.4s' }} />
                {isActive && (
                  <div style={{
                    position: 'absolute', top: -3, width: 8, height: 8, borderRadius: '50%',
                    background: stage.color,
                    animation: 'flowRight 1.5s infinite ease-in-out',
                  }} />
                )}
              </div>
            )}
          </div>
        )
      })}
      <style>{`
        @keyframes pipelinePulse { 0%,100% { box-shadow: 0 0 4px currentColor } 50% { box-shadow: 0 0 12px currentColor } }
        @keyframes flowRight { 0% { left: 0%; opacity: 0 } 20% { opacity: 1 } 80% { opacity: 1 } 100% { left: 100%; opacity: 0 } }
      `}</style>
    </div>
  )
}

export default RemediationPipeline
