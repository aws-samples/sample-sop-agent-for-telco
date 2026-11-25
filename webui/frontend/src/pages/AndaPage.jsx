import { useState, useEffect, useRef } from 'react'
import {
  Row, Col, Card, Tag, Skeleton, Alert,
  Steps, Descriptions, Badge, Timeline,
} from 'antd'
import {
  DeploymentUnitOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  ArrowRightOutlined,
  InfoCircleOutlined,
  LoadingOutlined,
  CodeOutlined,
} from '@ant-design/icons'
import { getAndaActiveDeployment, getAgentsReasoning } from '../services/api'

const STATUS_COLORS = {
  success: '#52c41a',
  completed: '#52c41a',
  running: '#1890FF',
  pending: '#FA8C16',
  failed: '#ff4d4f',
  error: '#ff4d4f',
  waiting: '#8c8c8c',
  skipped: '#d9d9d9',
}

const STEP_ICON = {
  success: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  failed: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
  running: <LoadingOutlined style={{ color: '#1890FF' }} />,
  info: <CodeOutlined style={{ color: '#8c8c8c' }} />,
}

// ─── SOP Live Steps Panel ───────────────────────────────────────────────────

const SopStepsPanel = ({ deployment }) => {
  const [steps, setSteps] = useState([])
  const bottomRef = useRef(null)

  useEffect(() => {
    if (!deployment?.active) return

    const poll = () => {
      getAgentsReasoning()
        .then(data => {
          const entries = data?.entries || []
          // Filter for ANDA deploy steps only
          const andaSteps = entries.filter(e =>
            e.agent === 'anda' || e.message?.includes('Step ')
          )
          setSteps(andaSteps)
        })
        .catch(() => {})
    }

    poll()
    const t = setInterval(poll, 5000) // Fast poll during active deployment
    return () => clearInterval(t)
  }, [deployment?.active])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [steps.length])

  if (!deployment?.active) return null
  if (steps.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '12px 0', color: '#8c8c8c', fontSize: 12 }}>
        <LoadingOutlined style={{ marginRight: 6 }} />
        Waiting for SOP execution steps...
      </div>
    )
  }

  // Show sopExecution metadata if available
  const sopExec = deployment.sop_execution || {}
  const nfExec = sopExec[deployment.nf] || Object.values(sopExec)[0] || {}

  return (
    <div>
      {/* Step counter + elapsed */}
      {nfExec.stepsExecuted && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12, fontSize: 12, color: '#8c8c8c' }}>
          <span><CodeOutlined /> {nfExec.stepsExecuted} steps executed</span>
          {nfExec.elapsed && <span><ClockCircleOutlined /> {nfExec.elapsed}</span>}
        </div>
      )}

      {/* Live step timeline */}
      <div style={{ maxHeight: 280, overflowY: 'auto', paddingRight: 4 }}>
        <Timeline
          items={steps.slice(-15).map((step, i) => ({
            dot: STEP_ICON[step.status] || STEP_ICON.info,
            children: (
              <div key={i}>
                <div style={{ fontSize: 12, fontWeight: 500 }}>{step.message}</div>
                {step.detail && (
                  <div style={{
                    fontSize: 11,
                    color: '#666',
                    background: '#fafafa',
                    borderRadius: 4,
                    padding: '3px 6px',
                    marginTop: 2,
                    fontFamily: 'monospace',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    maxWidth: 400,
                  }}>
                    {step.detail}
                  </div>
                )}
              </div>
            ),
          }))}
        />
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

// ─── Deployment Pipeline ────────────────────────────────────────────────────

const DeploymentPipeline = ({ deployment, loading }) => {
  if (loading) return <Skeleton active paragraph={{ rows: 4 }} />

  if (!deployment || !deployment.active) {
    return (
      <div style={{ textAlign: 'center', padding: '24px 0' }}>
        <CheckCircleOutlined style={{ fontSize: 40, color: '#52c41a', display: 'block', marginBottom: 12 }} />
        <div style={{ fontSize: 16, fontWeight: 600, color: '#52c41a' }}>No active deployment</div>
        <div style={{ fontSize: 13, color: '#8c8c8c', marginTop: 4 }}>Fleet is stable — no deployment in progress</div>
      </div>
    )
  }

  const stages = deployment.stages || []
  const currentStageIdx = stages.findIndex(s =>
    s.status === 'running' || s.status === 'in_progress' || s.status === 'active'
  )

  return (
    <div>
      <Alert
        type="info"
        showIcon
        message={
          <span style={{ fontWeight: 600 }}>
            Deploying: <Tag color="blue">{deployment.nf}</Tag>
            {deployment.intent && <Tag color="purple">{deployment.intent}</Tag>}
          </span>
        }
        description={deployment.reasoning && (
          <div style={{ background: '#F3E5F5', borderRadius: 4, padding: '6px 10px', marginTop: 8, borderLeft: '3px solid #CE93D8' }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: '#6A1B9A', marginRight: 6 }}>Change Agent reasoning:</span>
            <span style={{ fontSize: 12, color: '#333' }}>{deployment.reasoning}</span>
          </div>
        )}
        style={{ marginBottom: 16, borderRadius: 6 }}
      />

      {stages.length > 0 && (
        <Steps
          current={currentStageIdx >= 0 ? currentStageIdx : stages.filter(s => s.status === 'completed' || s.status === 'success' || s.status === 'done').length}
          size="small"
          style={{ marginBottom: 16 }}
          items={stages.map((stage, i) => {
            const stageColor = STATUS_COLORS[stage.status] || '#8c8c8c'
            return {
              title: stage.name || `Stage ${i + 1}`,
              description: (
                <span>
                  <Tag
                    style={{
                      fontSize: 10,
                      color: stageColor,
                      border: `1px solid ${stageColor}`,
                      background: `${stageColor}15`,
                    }}
                  >
                    {stage.status}
                  </Tag>
                  {stage.detail && (
                    <span style={{ fontSize: 11, color: '#8c8c8c', display: 'block', marginTop: 2 }}>
                      {stage.detail}
                    </span>
                  )}
                </span>
              ),
              status: stage.status === 'success' || stage.status === 'completed' || stage.status === 'done'
                ? 'finish'
                : stage.status === 'running' || stage.status === 'in_progress' || stage.status === 'active'
                ? 'process'
                : stage.status === 'failed' || stage.status === 'error'
                ? 'error'
                : 'wait',
            }
          })}
        />
      )}

      {(deployment.watching || deployment.safety_net) && (
        <Row gutter={8} style={{ marginTop: 12 }}>
          {deployment.watching && (
            <Col>
              <Tag icon={<InfoCircleOutlined />} color="blue">
                Watching: {deployment.watching}
              </Tag>
            </Col>
          )}
          {deployment.safety_net && (
            <Col>
              <Tag icon={<CheckCircleOutlined />} color="green">
                Safety net: {deployment.safety_net}
              </Tag>
            </Col>
          )}
        </Row>
      )}
    </div>
  )
}

// ─── Main Page ──────────────────────────────────────────────────────────────

const AndaPage = () => {
  const [deployment, setDeployment] = useState(null)
  const [deploymentLoading, setDeploymentLoading] = useState(true)

  const loadData = () => {
    getAndaActiveDeployment()
      .then(data => { setDeployment(data); setDeploymentLoading(false) })
      .catch(() => setDeploymentLoading(false))
  }

  useEffect(() => {
    loadData()
    // Poll faster (10s) when deployment is active, otherwise 30s
    const interval = deployment?.active ? 10000 : 30000
    const t = setInterval(loadData, interval)
    return () => clearInterval(t)
  }, [deployment?.active])

  return (
    <div>
      <Row gutter={[16, 16]}>
        {/* Deployment Pipeline */}
        <Col xs={24} lg={12}>
          <Card
            title={
              <span>
                <DeploymentUnitOutlined style={{ marginRight: 8, color: '#1890FF' }} />
                Active Deployment Pipeline
              </span>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
          >
            <DeploymentPipeline deployment={deployment} loading={deploymentLoading} />
          </Card>
        </Col>

        {/* Live SOP Execution Steps */}
        <Col xs={24} lg={12}>
          <Card
            title={
              <span>
                <CodeOutlined style={{ marginRight: 8, color: '#722ed1' }} />
                SOP Execution Progress
                {deployment?.active && (
                  <Tag color="blue" style={{ marginLeft: 8, fontSize: 10 }}>LIVE</Tag>
                )}
              </span>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
            extra={deployment?.active && (
              <Badge status="processing" text={<span style={{ fontSize: 11 }}>Executing</span>} />
            )}
          >
            {deployment?.active ? (
              <SopStepsPanel deployment={deployment} />
            ) : (
              <div style={{ textAlign: 'center', padding: '24px 0' }}>
                <CheckCircleOutlined style={{ fontSize: 32, color: '#52c41a', display: 'block', marginBottom: 8 }} />
                <div style={{ fontSize: 13, color: '#8c8c8c' }}>No SOP executing — fleet idle</div>
              </div>
            )}
          </Card>
        </Col>

      </Row>
    </div>
  )
}

export default AndaPage
