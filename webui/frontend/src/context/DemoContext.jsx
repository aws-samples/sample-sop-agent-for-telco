import { createContext, useContext, useState } from 'react'

const DemoContext = createContext({ isDemoMode: false, toggleDemo: () => {} })

export const useDemoMode = () => useContext(DemoContext)

export const MOCK_IMPACT_DATA = {
  lastReconciled: new Date().toISOString(),
  completeness: 'full',
  graphHash: 'demo0001',
  site: { name: 'edge-site-01', totalNodes: 3, totalNFs: 7 },
  nodes: [
    {
      name: 'worker-01', hostedNFs: ['du-1'],
      impactIfDown: { severity: 'Critical', affectedNFs: [
        { name: 'du-1', impact: 'down', reason: 'hosted on worker-01' },
        { name: 'cu-cp-1', impact: 'unreachable', reason: 'no path after worker-01 removal' },
        { name: 'cu-up-1', impact: 'unreachable', reason: 'no path after worker-01 removal' },
      ]},
      redundancy: { hasFailover: false, reason: 'single point or single replica' },
    },
    {
      name: 'worker-02', hostedNFs: ['cu-cp-1', 'cu-up-1'],
      impactIfDown: { severity: 'High', affectedNFs: [
        { name: 'cu-cp-1', impact: 'down', reason: 'hosted on worker-02' },
        { name: 'cu-up-1', impact: 'down', reason: 'hosted on worker-02' },
      ]},
      redundancy: { hasFailover: false, reason: 'single point or single replica' },
    },
    {
      name: 'worker-03', hostedNFs: ['amf-1', 'smf-1', 'upf-1'],
      impactIfDown: { severity: 'Critical', affectedNFs: [
        { name: 'amf-1', impact: 'down', reason: 'hosted on worker-03' },
        { name: 'smf-1', impact: 'down', reason: 'hosted on worker-03' },
        { name: 'upf-1', impact: 'down', reason: 'hosted on worker-03' },
      ]},
      redundancy: { hasFailover: false, reason: 'single point or single replica' },
    },
  ],
  singlePointsOfFailure: {
    connectivity: [{ node: 'worker-02', reason: 'articulation point in physical graph', remediation: 'add redundant link' }],
    capacity: [
      { node: 'worker-01', nfs: ['du-1'], reason: 'all NFs single-replica', remediation: 'increase replicas or spread across nodes' },
      { node: 'worker-03', nfs: ['amf-1', 'smf-1', 'upf-1'], reason: 'all NFs single-replica', remediation: 'increase replicas' },
    ],
  },
  cascadeChains: [
    { trigger: 'worker-01', chain: ['du-1', 'cu-cp-1', 'cu-up-1'] },
    { trigger: 'worker-02', chain: ['cu-cp-1', 'cu-up-1', 'amf-1'] },
    { trigger: 'worker-03', chain: ['amf-1', 'smf-1', 'upf-1'] },
  ],
}

export const MOCK_REASONING_FEED = [
  { time: '14:32:01', agent: 'ANRA', message: 'Detected thermal anomaly on worker-01 — fan RPM dropped 40%' },
  { time: '14:32:03', agent: 'ANRA', message: 'Checking BMC SEL for hardware events via Redfish...' },
  { time: '14:32:05', agent: 'ANRA', message: 'Root cause: Fan-3 failure. Recommending workload migration.' },
  { time: '14:32:08', agent: 'ANPA', message: 'VirtualMedia mount on worker-04 succeeded — HookOS booting' },
  { time: '14:32:10', agent: 'ANDA', message: 'Canary deployment gnb v24.10 healthy at 90% — promoting' },
  { time: '14:32:15', agent: 'ANRA', message: 'Blast radius: du-1 DOWN, cu-cp-1 UNREACHABLE — initiating drain' },
  { time: '14:32:18', agent: 'ANPA', message: 'Tinkerbell workflow STATE_SUCCESS — node joining cluster' },
  { time: '14:32:22', agent: 'ANDA', message: 'NF migration complete: du-1 rescheduled to worker-04' },
  { time: '14:32:25', agent: 'ANRA', message: 'All KPIs recovered. Incident auto-closed.' },
]

export const DemoProvider = ({ children }) => {
  const [isDemoMode, setIsDemoMode] = useState(false)
  const toggleDemo = () => setIsDemoMode(prev => !prev)

  return (
    <DemoContext.Provider value={{ isDemoMode, toggleDemo }}>
      {children}
    </DemoContext.Provider>
  )
}

export default DemoContext
