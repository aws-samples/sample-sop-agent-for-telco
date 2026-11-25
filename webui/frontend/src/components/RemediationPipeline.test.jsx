import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import RemediationPipeline, { incidentStages } from './RemediationPipeline'

const ev = (stage, message) => ({ stage, message, timestamp: '2026-11-25T19:00:00Z' })

// The AMF incident as the monitor now logs it.
const AMF_INCIDENT = [
  ev('detect', 'free5gc_nf_unavailable fired (critical)'),
  ev('correlate', 'free5gc_nf_unavailable: root cause; SOP proposed for your approval'),
  ev('resolve', 'SOP: /app/sops/day2-remediate/core/free5gc-nf-unavailable.md'),
  ev('detect', 'free5gc_registration_unavailable fired (critical)'),
  ev('correlate', 'free5gc_registration_unavailable: symptom of free5gc_nf_unavailable, suppressed'),
]

describe('RemediationPipeline', () => {
  it('follows the latest root-cause incident, not the latest event', () => {
    const { alarm, state } = incidentStages(AMF_INCIDENT)
    expect(alarm).toBe('free5gc_nf_unavailable')
    expect(state).toMatchObject({ detect: 'done', correlate: 'done', resolve: 'done', enrich: 'skipped', approve: 'current' })
  })

  it('reaches Execute and Clear after approval, plan completion and the alert clearing', () => {
    const { state } = incidentStages([
      ...AMF_INCIDENT,
      ev('execute', 'Operator approved — executing SOP for free5gc_nf_unavailable'),
      ev('execute', "Created DeploymentPlan 'anra-amf-1' — ANDA executing SOP for amf"),
      ev('execute', 'Network Change Agent: plan anra-amf-1 Completed in 86s, 16 steps'),
      ev('clear', 'free5gc_nf_unavailable cleared'),
    ])
    expect(state).toMatchObject({ approve: 'done', execute: 'done', clear: 'done' })
  })

  it('marks Enrich pending for a generated SOP', () => {
    const { state } = incidentStages([
      ev('detect', 'Free5GCWorkshopPipelineTest fired (info)'),
      ev('correlate', 'Free5GCWorkshopPipelineTest: root cause; SOP proposed for your approval'),
      ev('resolve', 'SOP: generating...'),
    ])
    expect(state.enrich).toBe('current')
  })

  it('renders the stages and the incident name', () => {
    render(<RemediationPipeline activity={AMF_INCIDENT} />)
    expect(screen.getByText('free5gc_nf_unavailable')).toBeTruthy()
    expect(screen.getByTestId('stage-enrich').dataset.state).toBe('skipped')
    expect(screen.getByText('skipped: reviewed SOP')).toBeTruthy()
    expect(screen.queryByText('19 SOPs + generate')).toBeNull()
  })

  it('says when there is no incident', () => {
    render(<RemediationPipeline activity={[]} />)
    expect(screen.getByText('No incident yet')).toBeTruthy()
  })
})
