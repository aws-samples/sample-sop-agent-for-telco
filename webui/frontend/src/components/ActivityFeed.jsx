const STAGE_COLORS = {
  collect: '#8c8c8c', detect: '#f5222d', correlate: '#722ed1',
  resolve: '#1890ff', enrich: '#fa8c16', execute: '#52c41a', reeval: '#faad14',
}
const STATUS_ICON = { info: '○', success: '✅', warning: '⚠️', error: '❌' }

const ActivityFeed = ({ activity = [] }) => {
  if (activity.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '24px 0', color: '#bfbfbf' }}>
        <div style={{ fontSize: 13 }}>Idle — monitoring 8,000+ metrics...</div>
        <div style={{ marginTop: 8, height: 3, background: '#f0f0f0', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ width: '30%', height: '100%', background: '#d9d9d9', borderRadius: 2, animation: 'idleSweep 3s infinite ease-in-out' }} />
        </div>
        <style>{`@keyframes idleSweep { 0% { margin-left: 0 } 50% { margin-left: 70% } 100% { margin-left: 0 } }`}</style>
      </div>
    )
  }

  return (
    <div style={{ maxHeight: 280, overflowY: 'auto', fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 12 }}>
      {[...activity].reverse().map((a, i) => {
        const color = STAGE_COLORS[a.stage] || '#999'
        const icon = STATUS_ICON[a.status] || '○'
        const time = a.timestamp ? new Date(a.timestamp).toLocaleTimeString() : ''
        return (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px',
            borderBottom: '1px solid #f5f5f5',
            animation: i === 0 ? 'fadeIn 0.3s ease' : 'none',
          }}>
            <span style={{ color: '#bfbfbf', fontSize: 11, minWidth: 65 }}>{time}</span>
            <span style={{
              width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0,
              boxShadow: i === 0 ? `0 0 6px ${color}` : 'none',
            }} />
            <span style={{ color, fontWeight: 600, minWidth: 70, textTransform: 'uppercase', fontSize: 10 }}>{a.stage}</span>
            <span style={{ color: '#434343', flex: 1 }}>{a.message}</span>
            <span style={{ fontSize: 11 }}>{icon}</span>
          </div>
        )
      })}
      <style>{`@keyframes fadeIn { from { opacity: 0; transform: translateY(-4px) } to { opacity: 1; transform: translateY(0) } }`}</style>
    </div>
  )
}

export default ActivityFeed
