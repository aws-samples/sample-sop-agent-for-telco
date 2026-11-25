import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import SopMarkdown from './SopMarkdown'

describe('SopMarkdown', () => {
  it('renders headings, tables and code blocks instead of raw markdown', () => {
    const { container } = render(<SopMarkdown content={'# Remediate\n\n## Step 1\n\n```bash\nkubectl get pods\n```\n\n| Cause | Fix |\n|---|---|\n| scale-down | scale to 1 |\n\n<script>alert(1)</script>'} />)
    expect(container.querySelector('h1').textContent).toBe('Remediate')
    expect(container.querySelector('h2').textContent).toBe('Step 1')
    expect(container.querySelector('pre code').textContent).toContain('kubectl get pods')
    expect(container.querySelector('table td').textContent).toBe('scale-down')
    expect(container.querySelector('script')).toBeNull()
    expect(container.textContent).not.toContain('## Step 1')
  })
})
