import { useState, useEffect, useCallback, useMemo } from 'react'
import ReactFlow, { Background, Controls, MiniMap, MarkerType, Handle, Position } from 'reactflow'
import 'reactflow/dist/style.css'
import { Badge, Tag, Tooltip, Spin, Alert, Drawer, List, Typography } from 'antd'
import { WarningOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { getTopologyImpact } from '../services/api'
import { useDemoMode, MOCK_IMPACT_DATA } from '../context/DemoContext'

const { Text } = Typography

const SEVERITY_COLORS = { Critical: '#f5222d', High: '#fa8c16', Medium: '#faad14' }
const LAYER_COLORS = { physical: '#1890ff', logical: '#52c41a', hosts: '#722ed1' }

const ServerNode = ({ data }) => {
  const isSpof = data.isSpof
  const severity = data.severity
  const borderColor = data.selected ? '#f5222d' : isSpof ? '#fa8c16' : '#1890ff'
  const bgColor = data.selected ? '#fff1f0' : '#f0f7ff'

  return (
    <div style={{
      padding: '12px 16px', borderRadius: 8, border: `2px solid ${borderColor}`,
      background: bgColor, minWidth: 140, textAlign: 'center', position: 'relative',
    }}>
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      {isSpof && (
        <Tooltip title={`SPOF: ${data.spofReason}`}>
          <WarningOutlined style={{ position: 'absolute', top: 4, right: 4, color: '#fa8c16', fontSize: 14 }} />
        </Tooltip>
      )}
      <div style={{ fontWeight: 700, fontSize: 13 }}>{data.label}</div>
      <div style={{ fontSize: 11, color: '#666', marginTop: 4 }}>
        {data.hostedNFs?.length || 0} NFs hosted
      </div>
      {severity && (
        <Tag color={SEVERITY_COLORS[severity]} style={{ marginTop: 6, fontSize: 10 }}>
          {severity} Impact
        </Tag>
      )}
      {data.hasFailover && (
        <CheckCircleOutlined style={{ position: 'absolute', top: 4, left: 4, color: '#52c41a', fontSize: 12 }} />
      )}
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

const NfNode = ({ data }) => {
  const borderColor = data.impact === 'down' ? '#f5222d' : data.impact === 'unreachable' ? '#fa8c16' : '#52c41a'
  const bgColor = data.impact === 'down' ? '#fff1f0' : data.impact === 'unreachable' ? '#fff7e6' : '#f6ffed'

  return (
    <div style={{
      padding: '8px 12px', borderRadius: 6, border: `1.5px solid ${borderColor}`,
      background: bgColor, minWidth: 80, textAlign: 'center',
    }}>
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <div style={{ fontWeight: 600, fontSize: 11 }}>{data.label}</div>
      {data.impact && (
        <div style={{ fontSize: 10, color: borderColor, marginTop: 2 }}>
          {data.impact === 'down' ? <CloseCircleOutlined /> : <WarningOutlined />} {data.impact}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
    </div>
  )
}

const nodeTypes = { server: ServerNode, nf: NfNode }

const ImpactMap = ({ onNodeSelect, selectedAlarmNode }) => {
  const { isDemoMode } = useDemoMode()
  const [impactData, setImpactData] = useState(null)
  const [error, setError] = useState(null)
  const [selectedServer, setSelectedServer] = useState(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  useEffect(() => {
    setSelectedServer(null)
    setDrawerOpen(false)
    if (isDemoMode) {
      setImpactData(MOCK_IMPACT_DATA)
      setError(null)
      return
    }
    const load = () => getTopologyImpact()
      .then(d => { setImpactData(d); setError(null) })
      .catch(e => setError(e.message))
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [isDemoMode])

  useEffect(() => {
    if (selectedAlarmNode) {
      setSelectedServer(selectedAlarmNode)
      setDrawerOpen(true)
    }
  }, [selectedAlarmNode])

  const { nodes, edges } = useMemo(() => {
    if (!impactData) return { nodes: [], edges: [] }

    const status = impactData
    const serverNodes = status.nodes || []
    const spofs = [
      ...(status.singlePointsOfFailure?.connectivity || []),
      ...(status.singlePointsOfFailure?.capacity || []),
    ]
    const spofSet = new Set(spofs.map(s => s.node))
    const spofReasons = Object.fromEntries(spofs.map(s => [s.node, s.reason]))

    const selectedImpact = selectedServer
      ? serverNodes.find(n => n.name === selectedServer)?.impactIfDown
      : null
    const affectedNfSet = new Set((selectedImpact?.affectedNFs || []).map(a => a.name))
    const affectedMap = Object.fromEntries((selectedImpact?.affectedNFs || []).map(a => [a.name, a.impact]))

    const flowNodes = []
    const flowEdges = []
    const allNfs = new Set()

    serverNodes.forEach((srv, i) => {
      flowNodes.push({
        id: srv.name,
        type: 'server',
        position: { x: 200 * i, y: 50 },
        data: {
          label: srv.name,
          hostedNFs: srv.hostedNFs,
          isSpof: spofSet.has(srv.name),
          spofReason: spofReasons[srv.name] || '',
          severity: selectedServer === srv.name ? selectedImpact?.severity : null,
          selected: selectedServer === srv.name,
          hasFailover: srv.redundancy?.hasFailover,
        },
      })

      ;(srv.hostedNFs || []).forEach((nf, j) => {
        if (!allNfs.has(nf)) {
          allNfs.add(nf)
          flowNodes.push({
            id: nf,
            type: 'nf',
            position: { x: 200 * i + (j % 2) * 100 - 25, y: 200 + Math.floor(j / 2) * 70 },
            data: {
              label: nf,
              impact: affectedMap[nf] || null,
            },
          })
        }
        flowEdges.push({
          id: `${srv.name}-${nf}`,
          source: srv.name,
          target: nf,
          style: { stroke: LAYER_COLORS.hosts, strokeWidth: 1.5 },
          markerEnd: { type: MarkerType.ArrowClosed, color: LAYER_COLORS.hosts },
          animated: affectedNfSet.has(nf),
        })
      })
    })

    // Cascade chain edges (physical)
    ;(status.cascadeChains || []).forEach(chain => {
      chain.chain.forEach((target, idx) => {
        const source = idx === 0 ? chain.trigger : chain.chain[idx - 1]
        if (flowNodes.find(n => n.id === source) && flowNodes.find(n => n.id === target)) {
          const edgeId = `cascade-${source}-${target}`
          if (!flowEdges.find(e => e.source === source && e.target === target)) {
            flowEdges.push({
              id: edgeId,
              source,
              target,
              style: { stroke: LAYER_COLORS.physical, strokeWidth: 2, strokeDasharray: '5 5' },
              animated: selectedServer === chain.trigger,
            })
          }
        }
      })
    })

    return { nodes: flowNodes, edges: flowEdges }
  }, [impactData, selectedServer])

  const onNodeClick = useCallback((_, node) => {
    if (node.type === 'server') {
      const next = selectedServer === node.id ? null : node.id
      setSelectedServer(next)
      setDrawerOpen(!!next)
      onNodeSelect?.(next)
    }
  }, [onNodeSelect, selectedServer])

  if (error) return <Alert type="error" message={`Failed to load impact data: ${error}`} />
  if (!impactData) return <Spin style={{ display: 'block', margin: '100px auto' }} />

  const selectedNodeData = (impactData.nodes || []).find(n => n.name === selectedServer)

  return (
    <div style={{ height: 500, border: '1px solid #f0f0f0', borderRadius: 8 }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
      >
        <Background color="#f0f0f0" gap={20} />
        <Controls />
        <MiniMap nodeColor={n => n.type === 'server' ? '#1890ff' : '#52c41a'} />
      </ReactFlow>

      <Drawer
        title={selectedServer ? `Blast Radius: ${selectedServer}` : 'Select a server'}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setSelectedServer(null) }}
        width={360}
      >
        {selectedNodeData && (
          <>
            <Tag color={SEVERITY_COLORS[selectedNodeData.impactIfDown?.severity]}>
              {selectedNodeData.impactIfDown?.severity} Severity
            </Tag>
            <div style={{ marginTop: 8, marginBottom: 16 }}>
              <Text type="secondary">
                {selectedNodeData.redundancy?.hasFailover ? 'Has failover' : 'No failover'} - {selectedNodeData.redundancy?.reason}
              </Text>
            </div>
            <List
              header={<Text strong>Affected Network Functions</Text>}
              dataSource={selectedNodeData.impactIfDown?.affectedNFs || []}
              renderItem={item => (
                <List.Item>
                  <List.Item.Meta
                    avatar={item.impact === 'down'
                      ? <CloseCircleOutlined style={{ color: '#f5222d', fontSize: 16 }} />
                      : <WarningOutlined style={{ color: '#fa8c16', fontSize: 16 }} />}
                    title={item.name}
                    description={item.reason}
                  />
                  <Tag color={item.impact === 'down' ? 'red' : 'orange'}>{item.impact}</Tag>
                </List.Item>
              )}
            />
          </>
        )}
      </Drawer>
    </div>
  )
}

export default ImpactMap
