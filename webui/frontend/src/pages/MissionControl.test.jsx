import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MissionControl from './MissionControl'

// ── Mock API module ──
const mockGetAgentsStatus = vi.fn()
const mockGetAgentsReasoning = vi.fn()
const mockGetAlarms = vi.fn()
const mockGetMetrics = vi.fn()
const mockGetMonitoringStats = vi.fn()
const mockGetAnraTrackRecord = vi.fn()
const mockGetAndaActiveDeployment = vi.fn()
const mockGetAndaFleetOpinions = vi.fn()
const mockGetInventory = vi.fn()
const mockGetProvisioningRequests = vi.fn()

vi.mock('../services/api', () => ({
  getAgentsStatus: (...args) => mockGetAgentsStatus(...args),
  getAgentsReasoning: (...args) => mockGetAgentsReasoning(...args),
  getAlarms: (...args) => mockGetAlarms(...args),
  getMetrics: (...args) => mockGetMetrics(...args),
  getMonitoringStats: (...args) => mockGetMonitoringStats(...args),
  getAnraIncidentCurrent: () => Promise.resolve(null),
  getAnraTrackRecord: (...args) => mockGetAnraTrackRecord(...args),
  getAndaActiveDeployment: (...args) => mockGetAndaActiveDeployment(...args),
  getAndaFleetOpinions: (...args) => mockGetAndaFleetOpinions(...args),
  getInventory: (...args) => mockGetInventory(...args),
  getProvisioningRequests: (...args) => mockGetProvisioningRequests(...args),
}))

// ── Mock useNavigate ──
const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

// ── Fixtures ──
const agentsFixture = {
  agents: [
    { name: 'ANPA', state: 'idle', detail: '' },
    { name: 'ANDA', state: 'active', detail: 'Deploying SMF v2.1' },
    { name: 'ANRA', state: 'thinking', detail: 'Correlating alarm #4821' },
  ],
}

const reasoningFixture = {
  entries: [
    { type: 'observe', agent: 'ANRA', message: 'InfluxDB query: 12 metrics collected', timestamp: '2026-06-15T17:09:42Z' },
    { type: 'decide', agent: 'ANDA', message: '3GPP drain: AMF sessions=0', timestamp: '2026-06-15T17:09:35Z' },
    { type: 'act', agent: 'ANPA', message: 'Provisioning request PR-003 completed', timestamp: '2026-06-15T17:09:28Z', status: 'success' },
  ],
}

const monitoringFixture = { tier1_rules: 12, tier2_metrics: 12, tier2_pct: 67 }
const alarmsFixture = { alarms: [{ id: 1 }, { id: 2 }], count: 2 }
const trackRecordFixture = { auto_resolved: 3, mttr_minutes: 4.2, sop_success_rate: 95 }
const inventoryFixture = { servers: [{ hostname: 'mi-026bd', phase: 'Ready' }, { hostname: 'mi-0c32a', phase: 'Ready' }] }
const provisioningFixture = { requests: [] }
const fleetFixture = { nfs: [{ name: 'AMF', status: 'Running', opinion: 'stable' }, { name: 'SMF', status: 'Running', opinion: 'upgrade' }, { name: 'UPF', status: 'Running', opinion: 'stable' }] }
const activeDeploymentFixture = { status: 'in-progress', nf: 'SMF', stage: 'draining' }

// ── Helpers ──
function renderMissionControl() {
  return render(
    <ConfigProvider>
      <MemoryRouter>
        <MissionControl />
      </MemoryRouter>
    </ConfigProvider>
  )
}

function mockAllApisSuccess() {
  mockGetAgentsStatus.mockResolvedValue(agentsFixture)
  mockGetAgentsReasoning.mockResolvedValue(reasoningFixture)
  mockGetAlarms.mockResolvedValue(alarmsFixture)
  mockGetMetrics.mockResolvedValue({ series: [] })
  mockGetMonitoringStats.mockResolvedValue(monitoringFixture)
  mockGetAnraTrackRecord.mockResolvedValue(trackRecordFixture)
  mockGetAndaActiveDeployment.mockResolvedValue(activeDeploymentFixture)
  mockGetAndaFleetOpinions.mockResolvedValue(fleetFixture)
  mockGetInventory.mockResolvedValue(inventoryFixture)
  mockGetProvisioningRequests.mockResolvedValue(provisioningFixture)
}

// ── Tests ──
describe('MissionControl', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows lifecycle banner before data resolves', () => {
    mockGetAgentsStatus.mockReturnValue(new Promise(() => {}))
    mockGetAgentsReasoning.mockReturnValue(new Promise(() => {}))
    mockGetAlarms.mockReturnValue(new Promise(() => {}))
    mockGetMetrics.mockReturnValue(new Promise(() => {}))
    mockGetMonitoringStats.mockReturnValue(new Promise(() => {}))
    mockGetAnraTrackRecord.mockReturnValue(new Promise(() => {}))
    mockGetAndaActiveDeployment.mockReturnValue(new Promise(() => {}))
    mockGetAndaFleetOpinions.mockReturnValue(new Promise(() => {}))
    mockGetInventory.mockReturnValue(new Promise(() => {}))
    mockGetProvisioningRequests.mockReturnValue(new Promise(() => {}))
    renderMissionControl()

    expect(screen.getByText('Autonomous Network Operations')).toBeInTheDocument()
    expect(screen.getByText(/3 Agents/)).toBeInTheDocument()
  })

  it('renders all three agent cards with correct day labels', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('Day 0 — Provisioning')).toBeInTheDocument()
      expect(screen.getByText('Day 1 — Deployment')).toBeInTheDocument()
      expect(screen.getByText('Day 2 — Remediation')).toBeInTheDocument()
    })
  })

  it('calls all required API functions on mount', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(mockGetAgentsStatus).toHaveBeenCalledTimes(1)
      expect(mockGetAgentsReasoning).toHaveBeenCalledTimes(1)
      expect(mockGetAlarms).toHaveBeenCalledTimes(1)
      expect(mockGetMetrics).toHaveBeenCalledTimes(1)
      expect(mockGetMonitoringStats).toHaveBeenCalledTimes(1)
      expect(mockGetAnraTrackRecord).toHaveBeenCalledTimes(1)
      expect(mockGetAndaActiveDeployment).toHaveBeenCalledTimes(1)
      expect(mockGetAndaFleetOpinions).toHaveBeenCalledTimes(1)
      expect(mockGetInventory).toHaveBeenCalledTimes(1)
      expect(mockGetProvisioningRequests).toHaveBeenCalledTimes(1)
    })
  })

  it('renders reasoning feed entries with correct OODA type tags', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('InfluxDB query: 12 metrics collected')).toBeInTheDocument()
    })

    expect(screen.getByText('3GPP drain: AMF sessions=0')).toBeInTheDocument()
    expect(screen.getByText('Provisioning request PR-003 completed')).toBeInTheDocument()
    expect(screen.getByText('Observe')).toBeInTheDocument()
    expect(screen.getByText('Decide')).toBeInTheDocument()
  })

  it('navigates to correct route when agent cards are clicked', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('Day 0 — Provisioning')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Day 0 — Provisioning').closest('.agent-hero-card'))
    expect(mockNavigate).toHaveBeenCalledWith('/anpa')

    fireEvent.click(screen.getByText('Day 1 — Deployment').closest('.agent-hero-card'))
    expect(mockNavigate).toHaveBeenCalledWith('/anda')

    fireEvent.click(screen.getByText('Day 2 — Remediation').closest('.agent-hero-card'))
    expect(mockNavigate).toHaveBeenCalledWith('/anra')
  })

  it('shows KPI cards with detection rules from API', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('T1:12 T2:12')).toBeInTheDocument()
    })

    expect(screen.getByText('Active Alarms')).toBeInTheDocument()
    expect(screen.getByText('Network Functions')).toBeInTheDocument()
    expect(screen.getByText('Detection Rules')).toBeInTheDocument()
  })

  it('renders NF grid with fallback when fleet opinions returns empty', async () => {
    mockAllApisSuccess()
    mockGetAndaFleetOpinions.mockResolvedValue({ nfs: [] })
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('5G Network Functions')).toBeInTheDocument()
    })
  })

  it('handles API errors gracefully without crashing', async () => {
    mockGetAgentsStatus.mockRejectedValue(new Error('Network error'))
    mockGetAgentsReasoning.mockRejectedValue(new Error('Network error'))
    mockGetAlarms.mockRejectedValue(new Error('timeout'))
    mockGetMetrics.mockResolvedValue({ series: [] })
    mockGetMonitoringStats.mockResolvedValue(monitoringFixture)
    mockGetAnraTrackRecord.mockResolvedValue(trackRecordFixture)
    mockGetAndaActiveDeployment.mockResolvedValue(null)
    mockGetAndaFleetOpinions.mockResolvedValue(null)
    mockGetInventory.mockResolvedValue(inventoryFixture)
    mockGetProvisioningRequests.mockResolvedValue(provisioningFixture)

    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('Autonomous Network Operations')).toBeInTheDocument()
      expect(screen.getByText('5G Network Functions')).toBeInTheDocument()
    })

    expect(screen.getByText(/agents are idle/i)).toBeInTheDocument()
  })

  it('displays agent activity details when active', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('Deploying SMF v2.1')).toBeInTheDocument()
      expect(screen.getByText('Correlating alarm #4821')).toBeInTheDocument()
    })
  })
})
