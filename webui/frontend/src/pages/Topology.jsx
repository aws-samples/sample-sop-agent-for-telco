import { useState, useEffect } from 'react'
import { Card, Tag, Badge, Spin, Alert, Row, Col, Statistic, Switch } from 'antd'
import { CloudServerOutlined, ApiOutlined, ApartmentOutlined } from '@ant-design/icons'
import axios from 'axios'

const NF_COLORS = {
  amf: '#bbdefb', smf: '#b3e5fc', nrf: '#b2dfdb', scp: '#c5cae9', upf: '#a5d6a7',
  ausf: '#f0f4c3', udm: '#dcedc8', udr: '#c8e6c9', pcf: '#ffe0b2', nssf: '#b2ebf2',
  du: '#f8bbd0', cu: '#f8bbd0', gnb: '#f8bbd0', anra: '#ffcc80',
}
const HIDDEN = new Set(['hss', 'mme', 'sgwc', 'sgwu', 'populate', 'ue', 'sim-ue', 'ru'])
const ANRA_NFS = new Set(['anra', 'telegraf-core', 'telegraf-hw', 'telegraf-ran', 'influxdb', 'grafana', 'mongodb'])

const Topology = () => {
  const [topo, setTopo] = useState(null)
  const [showAnra, setShowAnra] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const load = () => axios.get('/api/topology').then(r => { setTopo(r.data); setError(null) }).catch(e => setError(e.message))
    load(); const t = setInterval(load, 60000); return () => clearInterval(t)
  }, [])

  if (error) return <Alert type="error" message={error} />
  if (!topo) return <Spin style={{ display: 'block', margin: '100px auto' }} />

  const s = topo.summary || {}
  const byNode = {}
  ;(topo.nf_pods || []).forEach(p => {
    if (HIDDEN.has(p.nf)) return
    if (!showAnra && (ANRA_NFS.has(p.nf) || p.nf.startsWith('telegraf'))) return
    if (!byNode[p.node]) byNode[p.node] = []
    byNode[p.node].push(p)
  })
  const edgeNodes = (topo.k8s_nodes || []).filter(n => n.role === 'edge')
  const regionNodes = (topo.k8s_nodes || []).filter(n => n.role === 'region')

  const NodeCard = ({ node, color, border }) => {
    const pods = byNode[node.name] || []
    if (!pods.length) return null
    return (
      <Card size="small" style={{ border: `2px solid ${border}`, borderRadius: 10, marginBottom: 12, background: color }}>
        <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 8 }}>{node.ip}</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {pods.map(p => (
            <Tag key={p.name} color={NF_COLORS[p.nf] ? undefined : 'default'}
              style={{ background: NF_COLORS[p.nf] || '#f5f5f5', border: '1px solid #ddd', fontWeight: 600, fontSize: 11 }}>
              {p.nf.toUpperCase()}
            </Tag>
          ))}
        </div>
      </Card>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Row gutter={16}>
          <Col><Statistic title="Nodes" value={s.k8s_node_count || 0} prefix={<CloudServerOutlined />} /></Col>
          <Col><Statistic title="NFs" value={s.nf_count || 0} prefix={<ApiOutlined />} /></Col>
          <Col><Statistic title="Edges" value={s.edge_count || 0} prefix={<ApartmentOutlined />} /></Col>
        </Row>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 13, color: showAnra ? '#999' : '#1565c0' }}>5G Network</span>
          <Switch checked={showAnra} onChange={setShowAnra} />
          <span style={{ fontSize: 13, color: showAnra ? '#e65100' : '#999' }}>ANRA Overlay</span>
        </div>
      </div>

      <Row gutter={24}>
        <Col span={8}>
          <Card title={<span><img src="/aws-icons/outposts.svg" alt="edge" style={{ width: 20, height: 20, verticalAlign: 'middle', marginRight: 6 }} />Edge Site (Dell)</span>} bordered={false} style={{ borderRadius: 12, border: '2px dashed #ff9800' }}>
            {edgeNodes.map(n => <NodeCard key={n.name} node={n} color="#fff8f0" border="#ff9800" />)}
          </Card>
        </Col>
        <Col span={16}>
          <Card title="☁️ AWS Region (EKS)" bordered={false} style={{ borderRadius: 12, border: '2px dashed #1976d2' }}>
            <Row gutter={12}>
              {regionNodes.map(n => (
                <Col span={6} key={n.name}>
                  <NodeCard node={n} color="#f0f7ff" border="#90caf9" />
                </Col>
              ))}
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Topology
