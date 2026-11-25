import { render, screen, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const getApprovals = vi.fn()

vi.mock('../services/api', () => ({
  getApprovals: (...args) => getApprovals(...args),
  APPROVALS_CHANGED_EVENT: 'approvals-changed',
}))
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'admin' }, logout: vi.fn(), changePassword: vi.fn() }),
}))
vi.mock('../context/DemoContext', () => ({
  useDemoMode: () => ({ isDemoMode: false, toggleDemo: vi.fn() }),
}))

import DashboardLayout from './DashboardLayout'

describe('DashboardLayout approvals badge', () => {
  beforeEach(() => getApprovals.mockReset())

  it('refreshes the pending count as soon as a decision is made', async () => {
    getApprovals
      .mockResolvedValueOnce({ approvals: [{ status: 'pending' }] })
      .mockResolvedValue({ approvals: [{ status: 'rejected' }] })
    render(
      <MemoryRouter>
        <DashboardLayout><div /></DashboardLayout>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('1')).toBeTruthy())
    await act(async () => { window.dispatchEvent(new Event('approvals-changed')) })
    await waitFor(() => expect(screen.queryByText('1')).toBeNull())
    expect(getApprovals).toHaveBeenCalledTimes(2)
  })
})
