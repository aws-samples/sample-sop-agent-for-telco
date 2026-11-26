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
const trackRecordFixture = { incidents_handled: 1, completed: 1, auto_resolved: 1, mttr_minutes: 1.4, sop_success_rate: 1.0 }
const fleetFixture = { nfs: [
  { name: 'AMF', deployment: 'free5gc-amf-deployment', status: 'Running', detail: '1/1 available' },
  { name: 'SMF', deployment: 'free5gc-smf-deployment', status: 'Running', detail: '1/1 available' },
  { name: 'gNB/UE sim', deployment: 'packetrusher-packetrusher', status: 'Running', detail: '1/1 available' },
] }
const activeDeploymentFixture = { active: false, history: [
  { name: 'anra-amf-1', alarm: 'free5gc_nf_unavailable', nf: 'amf', phase: 'Completed', elapsed_seconds: 86, active: false },
] }

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
    renderMissionControl()

    expect(screen.getByText('Autonomous Network Operations')).toBeInTheDocument()
    expect(screen.getByText(/2 Agents/)).toBeInTheDocument()
  })

  it('renders the two participant-facing agent cards', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getAllByText('Network Assurance Agent').length).toBeGreaterThan(0)
      expect(screen.getAllByText('Network Change Agent').length).toBeGreaterThan(0)
      expect(screen.queryByText('Day 0 — Provisioning')).not.toBeInTheDocument()
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
    })
  })

  it('renders reasoning feed entries with correct OODA type tags', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('InfluxDB query: 12 metrics collected')).toBeInTheDocument()
    })

    expect(screen.getByText('3GPP drain: AMF sessions=0')).toBeInTheDocument()
    expect(screen.queryByText('Provisioning request PR-003 completed')).not.toBeInTheDocument()
    expect(screen.getByText('Observe')).toBeInTheDocument()
    expect(screen.getByText('Decide')).toBeInTheDocument()
  })

  it('navigates to correct route when agent cards are clicked', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getAllByText('Network Assurance Agent').length).toBeGreaterThan(0)
    })

    const assuranceCardLabel = screen.getAllByText('Network Assurance Agent')
      .find(element => element.closest('.agent-hero-card'))
    const changeCardLabel = screen.getAllByText('Network Change Agent')
      .find(element => element.closest('.agent-hero-card'))

    fireEvent.click(assuranceCardLabel.closest('.agent-hero-card'))
    expect(mockNavigate).toHaveBeenCalledWith('/anra')

    fireEvent.click(changeCardLabel.closest('.agent-hero-card'))
    expect(mockNavigate).toHaveBeenCalledWith('/anda')
  })

  it('shows KPI cards with detection rules from API', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('alert rules')).toBeInTheDocument()
    })

    expect(screen.getByText('Active Alarms')).toBeInTheDocument()
    expect(screen.getByText('Network Functions')).toBeInTheDocument()
    expect(screen.getByText('Detection Rules')).toBeInTheDocument()
  })

  it('shows "NF status unavailable" and no invented NFs when the list is empty', async () => {
    mockAllApisSuccess()
    mockGetAndaFleetOpinions.mockResolvedValue({ nfs: [], error: 'NF status unavailable' })
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('NF status unavailable')).toBeInTheDocument()
    })
    expect(screen.queryByTestId(/^nf-tile-/)).not.toBeInTheDocument()
    expect(screen.queryByText('SCP')).not.toBeInTheDocument()
  })

  it('renders one tile per NF with the health the API reports', async () => {
    mockAllApisSuccess()
    mockGetAndaFleetOpinions.mockResolvedValue({ nfs: [
      { name: 'AMF', status: 'Down', detail: '0/0 available' },
      { name: 'SMF', status: 'Running', detail: '1/1 available' },
    ] })
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByTestId('nf-tile-AMF')).toHaveAttribute('data-status', 'Down')
    })
    expect(screen.getByTestId('nf-tile-AMF').style.background).toBe('rgb(255, 241, 240)')
    expect(screen.getByTestId('nf-tile-SMF').style.background).toBe('rgb(246, 255, 237)')
  })

  it('shows real hand-offs and no invented collaboration', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByText('Recent hand-offs')).toBeInTheDocument()
    })
    expect(await screen.findByText('86s')).toBeInTheDocument()
    expect(screen.queryByText('Deployment change correlation')).not.toBeInTheDocument()
    expect(screen.queryByText('Cluster health pre-check')).not.toBeInTheDocument()
    expect(screen.queryByText('Detection Tiers')).not.toBeInTheDocument()
    expect(screen.queryByText(/baselined/)).not.toBeInTheDocument()
  })

  it('says "None yet" when nothing was handed off', async () => {
    mockAllApisSuccess()
    mockGetAndaActiveDeployment.mockResolvedValue({ active: false, history: [] })
    renderMissionControl()
    expect(await screen.findByText('None yet')).toBeInTheDocument()
  })

  it('has no Upgrades counter on the Network Change Agent card', async () => {
    mockAllApisSuccess()
    renderMissionControl()

    await waitFor(() => {
      expect(screen.getByTestId('nf-tile-AMF')).toBeInTheDocument()
    })
    expect(screen.queryByText('Upgrades')).not.toBeInTheDocument()
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
