import { useState, useEffect } from 'react'
import { Card, Table, Tag, Modal, Input } from 'antd'
import { FileTextOutlined, SearchOutlined } from '@ant-design/icons'
import axios from 'axios'

const SOPs = () => {
  const [sops, setSops] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [modal, setModal] = useState(null)
  const [content, setContent] = useState('')

  useEffect(() => { axios.get('/api/sops').then(r => { setSops(r.data.sops || []); setLoading(false) }).catch(() => setLoading(false)) }, [])

  const openSop = (path) => {
    setModal(path)
    axios.get(`/api/sops/${path}`).then(r => setContent(r.data.content || '')).catch(() => setContent('Failed to load'))
  }

  const filtered = sops.filter(s => s.title?.toLowerCase().includes(search.toLowerCase()) || s.path?.includes(search))

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 16 }}>{sops.length} SOPs</span>
        <Input prefix={<SearchOutlined />} placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)} style={{ width: 250 }} allowClear />
      </div>
      <Card bordered={false}>
        <Table dataSource={filtered} rowKey="path" loading={loading} size="small" pagination={{ pageSize: 15 }}
          columns={[
            { title: 'Title', dataIndex: 'title', render: (t, r) => <a onClick={() => openSop(r.path)}><FileTextOutlined /> {t}</a> },
            { title: 'Phase', dataIndex: 'phase', width: 120, render: p => <Tag color={p?.includes('day0') ? 'blue' : p?.includes('day1') ? 'green' : 'orange'}>{p}</Tag> },
            { title: 'Severity', dataIndex: 'severity', width: 90, render: s => s ? <Tag color={s === 'critical' ? 'red' : 'orange'}>{s}</Tag> : '-' },
          ]} />
      </Card>
      <Modal title={modal} open={!!modal} onCancel={() => setModal(null)} footer={null} width={700}>
        <pre style={{ whiteSpace: 'pre-wrap', fontSize: 13, maxHeight: '60vh', overflow: 'auto' }}>{content}</pre>
      </Modal>
    </div>
  )
}

export default SOPs
