import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import App from './App'

function renderWithProviders(ui) {
  return render(
    <ConfigProvider theme={{ token: { colorPrimary: '#1890ff', borderRadius: 6 } }}>
      <BrowserRouter>{ui}</BrowserRouter>
    </ConfigProvider>
  )
}

describe('App', () => {
  it('renders layout title and primary navigation labels', () => {
    renderWithProviders(<App />)
    expect(screen.getByText('Autonomous Network Remediation Agent')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByText('Alarms')).toBeInTheDocument()
    expect(screen.getByText('Ask ANRA')).toBeInTheDocument()
  })
})
