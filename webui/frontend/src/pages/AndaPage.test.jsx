import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

const getAndaFleetOpinions = vi.fn()

vi.mock('../services/api', () => ({
  getAndaActiveDeployment: () => Promise.resolve({ active: false }),
  getAgentsReasoning: () => Promise.resolve([]),
  getAndaFleetOpinions: (...args) => getAndaFleetOpinions(...args),
}))

import AndaPage from './AndaPage'

describe('Network Change Agent page', () => {
  it('shows SOP progress and no fleet cards', async () => {
    render(<AndaPage />)
    await waitFor(() => expect(screen.getByText(/No SOP executing/)).toBeTruthy())
    expect(screen.getByText('SOP Execution Progress')).toBeTruthy()
    expect(screen.queryByText('Fleet Version Summary')).toBeNull()
    expect(screen.queryByText('NF Fleet with Change Agent Opinions')).toBeNull()
    expect(screen.queryByText('Stable NFs')).toBeNull()
    expect(getAndaFleetOpinions).not.toHaveBeenCalled()
  })
})
