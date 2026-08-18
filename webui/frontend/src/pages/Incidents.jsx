import { useState, useEffect } from 'react'
import { Table, Tag, Spin, Alert, Card, Input, Space, Typography } from 'antd'
import { SearchOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getIncidents } from '../services/api'

const { Title } = Typography

const SEVERITY_COLORS = { critical: 'red', high: 'orange', medium: 'gold', low: 'blue' }
const STATUS_COLORS = { active: 'red', investigating: 'orange', resolved: 'green', closed: 'default' }

const Incidents = () => {
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    getIncidents()
      .then(data => {
        setIncidents(Array.isArray(data) ? data : data?.incidents || [])
        setLoading(false)
      })
      .catch(e => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  const filtered = incidents.filter(i =>
    !search || JSON.stringify(i).toLowerCase().includes(search.toLowerCase())
  )

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      render: (id) => <a onClick={(e) => { e.stopPropagation(); navigate(`/incidents/${id}`) }}>{id}</a>,
      width: 120,
    },
    {
      title: 'Title',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: 'Severity',
      dataIndex: 'severity',
      key: 'severity',
      render: (s) => <Tag color={SEVERITY_COLORS[s?.toLowerCase()] || 'default'}>{s || 'Unknown'}</Tag>,
      filters: [
        { text: 'Critical', value: 'critical' },
        { text: 'High', value: 'high' },
        { text: 'Medium', value: 'medium' },
        { text: 'Low', value: 'low' },
      ],
      onFilter: (value, record) => record.severity?.toLowerCase() === value,
      width: 100,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      render: (s) => <Tag color={STATUS_COLORS[s?.toLowerCase()] || 'default'}>{s || 'Unknown'}</Tag>,
      filters: [
        { text: 'Active', value: 'active' },
        { text: 'Investigating', value: 'investigating' },
        { text: 'Resolved', value: 'resolved' },
      ],
      onFilter: (value, record) => record.status?.toLowerCase() === value,
      width: 120,
    },
    {
      title: 'Affected NFs',
      dataIndex: 'affected_nfs',
      key: 'affected_nfs',
      render: (nfs) => (nfs || []).slice(0, 3).map(nf => <Tag key={nf}>{nf}</Tag>),
    },
    {
      title: 'Time',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (t) => t ? new Date(t).toLocaleString() : '-',
      sorter: (a, b) => new Date(a.created_at) - new Date(b.created_at),
      defaultSortOrder: 'descend',
      width: 180,
    },
  ]

  if (error) return <Alert type="error" message={error} />

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Title level={4} style={{ margin: 0 }}>
          <ThunderboltOutlined /> Incidents
        </Title>
        <Input
          prefix={<SearchOutlined />}
          placeholder="Search incidents..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ width: 300 }}
          allowClear
        />
      </Space>
      <Card bordered={false}>
        <Table
          columns={columns}
          dataSource={filtered}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 15, showSizeChanger: true }}
          onRow={(record) => ({
            onClick: () => navigate(`/incidents/${record.id}`),
            style: { cursor: 'pointer' },
          })}
        />
      </Card>
    </div>
  )
}

export default Incidents
