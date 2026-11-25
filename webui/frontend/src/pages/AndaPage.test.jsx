import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const getAndaActiveDeployment = vi.fn()
const getAndaFleetOpinions = vi.fn()

vi.mock('../services/api', () => ({
  getAndaActiveDeployment: (...args) => getAndaActiveDeployment(...args),
  getAndaFleetOpinions: (...args) => getAndaFleetOpinions(...args),
}))

import AndaPage from './AndaPage'

const DONE = {
  name: 'anra-amf-1795633892',
  alarm: 'free5gc_nf_unavailable',
  nf: 'amf',
  sop: 'day2-remediate/core/free5gc-nf-unavailable.md',
  phase: 'Completed',
  elapsed_seconds: 86,
  steps: 16,
  created: '2026-11-25T19:11:33Z',
  finished: '2026-11-25T19:12:59Z',
  reason: 'Operator approved remediation for alarm: free5gc_nf_unavailable',
}

describe('Network Change Agent page', () => {
  beforeEach(() => {
    getAndaActiveDeployment.mockReset()
    getAndaFleetOpinions.mockReset()
  })

  it('shows completed changes as history when nothing is running', async () => {
    getAndaActiveDeployment.mockResolvedValue({ active: false, history: [DONE] })
    render(<AndaPage />)
    await waitFor(() => expect(screen.getByText('No change running')).toBeTruthy())
    expect(screen.getByText('Recent changes')).toBeTruthy()
    expect(screen.getByText('free5gc_nf_unavailable')).toBeTruthy()
    expect(screen.getByText('Completed')).toBeTruthy()
    expect(screen.getByText('86s · 16 steps')).toBeTruthy()
    expect(screen.queryByText(/auto-rollback/)).toBeNull()
    expect(getAndaFleetOpinions).not.toHaveBeenCalled()
  })

  it('shows the plan that is running', async () => {
    getAndaActiveDeployment.mockResolvedValue({
      active: true,
      plan_name: 'anra-amf-2',
      nf: 'amf',
      stage: 'InProgress',
      alarm: 'free5gc_nf_unavailable',
      sop: 'day2-remediate/core/free5gc-nf-unavailable.md',
      reasoning: 'Operator approved remediation for alarm: free5gc_nf_unavailable',
      stages: [
        { name: 'Accepted', status: 'done' },
        { name: 'Running SOP', status: 'active' },
        { name: 'Done', status: 'pending' },
      ],
      history: [{ ...DONE, name: 'anra-amf-2', phase: 'InProgress', elapsed_seconds: null }],
    })
    render(<AndaPage />)
    await waitFor(() => expect(screen.getByText('anra-amf-2')).toBeTruthy())
    expect(screen.getAllByText('InProgress').length).toBeGreaterThan(0)
    expect(screen.getByText('Running SOP')).toBeTruthy()
  })

  it('says when there is no history yet', async () => {
    getAndaActiveDeployment.mockResolvedValue({ active: false, history: [] })
    render(<AndaPage />)
    await waitFor(() => expect(screen.getByText(/No changes yet/)).toBeTruthy())
  })
})
