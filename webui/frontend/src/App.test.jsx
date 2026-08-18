import { render, screen } from '@testing-library/react'
import App from './App'

describe('App', () => {
  it('renders layout title and primary navigation labels', () => {
    render(<App />)
    expect(screen.getByText('ANO')).toBeInTheDocument()
    expect(screen.getAllByText('Mission Control').length).toBeGreaterThan(0)
  })
})
