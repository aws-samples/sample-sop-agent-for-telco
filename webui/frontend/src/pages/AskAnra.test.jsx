import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import axios from 'axios'
import AskAnra from './AskAnra'

vi.mock('axios')
// jsdom does not implement scrollIntoView, which the chat calls on each message.
Element.prototype.scrollIntoView = vi.fn()

describe('AskAnra', () => {
  beforeEach(() => sessionStorage.clear())

  it('renders agent replies as markdown, including tables, without raw HTML', async () => {
    axios.post.mockResolvedValue({
      data: {
        response: '**Active Alarms: 1**\n\n| Alarm Name | Severity |\n|---|---|\n| free5gc_nf_unavailable | critical |\n\n<b>raw</b>',
      },
    })
    const { container } = render(<AskAnra />)
    fireEvent.click(screen.getByText('What alarms are active?'))
    await waitFor(() => expect(container.querySelector('table')).toBeTruthy())
    expect(screen.getByText('Active Alarms: 1').tagName).toBe('STRONG')
    expect(screen.getByText('free5gc_nf_unavailable').tagName).toBe('TD')
    expect(container.querySelector('.ask-agent-reply b')).toBeNull()
    // The question the user asked stays plain text.
    expect(screen.getAllByText('What alarms are active?').length).toBeGreaterThan(0)
  })

  it('keeps the conversation when the page is left and opened again', async () => {
    axios.post.mockResolvedValue({ data: { response: 'No alarms are firing.' } })
    const first = render(<AskAnra />)
    fireEvent.click(screen.getByText('What alarms are active?'))
    await waitFor(() => expect(screen.getByText('No alarms are firing.')).toBeTruthy())
    first.unmount()

    render(<AskAnra />)
    expect(screen.getByText('No alarms are firing.')).toBeTruthy()
    expect(screen.getAllByText('What alarms are active?').length).toBeGreaterThan(1)
  })
})
