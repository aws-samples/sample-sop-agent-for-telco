import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Dashboard from './Dashboard'

const { mockAxiosGet } = vi.hoisted(() => ({ mockAxiosGet: vi.fn() }))

vi.mock('axios', () => ({
  default: { get: mockAxiosGet },
}))

const apiFixtures = {
  topology: {
    summary: { k8s_node_count: 0, nf_count: 0, edge_count: 0, config_node_count: 0 },
    k8s_nodes: [],
    config_nodes: [],
  },
  alarms: { alarms: [], count: 0 },
  executions: { executions: [], count: 0 },
  monitoring: {
    status: 'ok',
    detail: null,
    tier1_rules: 5,
    tier2_metrics: 120,
    tier2_ready: 10,
    tier2_pct: 35,
    tier3_cooldown: 300,
    alarm_definitions: 5,
    sources: { ran: true, core: true, hardware: false, os: true },
  },
}

function mockApi() {
  mockAxiosGet.mockImplementation((url) => {
    const p = String(url)
    if (p.includes('/api/topology')) return Promise.resolve({ data: apiFixtures.topology })
    if (p.includes('/api/alarms')) return Promise.resolve({ data: apiFixtures.alarms })
    if (p.includes('/api/executions')) return Promise.resolve({ data: apiFixtures.executions })
    if (p.includes('/api/monitoring-stats')) return Promise.resolve({ data: apiFixtures.monitoring })
    return Promise.reject(new Error('unexpected URL: ' + p))
  })
}

describe('Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApi()
  })

  it('requests core APIs and renders monitoring coverage', async () => {
    render(
      <ConfigProvider>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </ConfigProvider>
    )

    await waitFor(() => {
      expect(screen.getByText(/ANRA Pipeline/i)).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(screen.getByText('Monitoring Coverage')).toBeInTheDocument()
    })
    expect(screen.getByText('Infrastructure nodes')).toBeInTheDocument()
    expect(screen.getByText('System status')).toBeInTheDocument()
    expect(mockAxiosGet).toHaveBeenCalled()
    const calls = mockAxiosGet.mock.calls.map((c) => String(c[0]))
    expect(calls.some((u) => u.includes('/api/topology'))).toBe(true)
    expect(calls.some((u) => u.includes('/api/alarms'))).toBe(true)
    expect(calls.some((u) => u.includes('/api/executions'))).toBe(true)
    expect(calls.some((u) => u.includes('/api/monitoring-stats'))).toBe(true)
  })

  it('shows a warning when monitoring stats are degraded on the server', async () => {
    mockAxiosGet.mockImplementation((url) => {
      const p = String(url)
      if (p.includes('/api/topology')) return Promise.resolve({ data: apiFixtures.topology })
      if (p.includes('/api/alarms')) return Promise.resolve({ data: apiFixtures.alarms })
      if (p.includes('/api/executions')) return Promise.resolve({ data: apiFixtures.executions })
      if (p.includes('/api/monitoring-stats')) {
        return Promise.resolve({
          data: { ...apiFixtures.monitoring, status: 'degraded', detail: 'baselines' },
        })
      }
      return Promise.reject(new Error('unexpected URL: ' + p))
    })

    render(
      <ConfigProvider>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </ConfigProvider>
    )

    await waitFor(() => {
      expect(
        screen.getByText(/Monitoring coverage is partial: baselines/i)
      ).toBeInTheDocument()
    })
  })
})
