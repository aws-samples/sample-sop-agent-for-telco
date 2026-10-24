import { render, screen } from '@testing-library/react'
import App from './App'

describe('App', () => {
  it('renders layout title and primary navigation labels', () => {
    render(<App />)
    expect(screen.getByText('ANO')).toBeInTheDocument()
    expect(screen.getAllByText('Mission Control').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Network Assurance Agent').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Network Change Agent').length).toBeGreaterThan(0)
    expect(screen.getByText('Ask AI Agent')).toBeInTheDocument()
    expect(screen.queryByText('Incidents')).not.toBeInTheDocument()
    expect(screen.queryByText(/ANPA/)).not.toBeInTheDocument()
  })
})
