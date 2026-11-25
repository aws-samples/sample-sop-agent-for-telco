import { useState, useRef, useEffect } from 'react'
import { Card, Input, Button, Tag, Spin } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import axios from 'axios'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const SUGGESTIONS = ['What alarms are active?', 'Explain the last SOP execution', 'What is the network status?', 'What happened in the last hour?']

const AskAnra = () => {
  const [msgs, setMsgs] = useState([{ role: 'agent', text: "I'm the AI Network Operations Agent — ask me about alarms, SOPs, nodes, or service impact." }])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const endRef = useRef(null)

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])

  const send = (text = input) => {
    if (!text.trim()) return
    setMsgs(prev => [...prev, { role: 'user', text }])
    setInput('')
    setLoading(true)
    axios.post('/api/chat', { message: text })
      .then(r => setMsgs(prev => [...prev, { role: 'agent', text: r.data.response }]))
      .catch(e => setMsgs(prev => [...prev, { role: 'agent', text: `Error: ${e.message}` }]))
      .finally(() => setLoading(false))
  }

  return (
    <Card bordered={false} style={{ height: 'calc(100vh - 160px)', display: 'flex', flexDirection: 'column' }}
      bodyStyle={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 0 }}>
      <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
        {msgs.map((m, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
            {m.role === 'user' ? (
              <div style={{ maxWidth: '70%', padding: '10px 14px', borderRadius: 12, background: '#1890ff', color: '#fff', whiteSpace: 'pre-wrap' }}>{m.text}</div>
            ) : (
              // Agent replies are markdown. react-markdown does not render raw HTML,
              // so model output cannot inject markup into the dashboard.
              <div className="ask-agent-reply" style={{ maxWidth: '70%', padding: '10px 14px', borderRadius: 12, background: '#f5f5f5', color: '#000' }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
              </div>
            )}
          </div>
        ))}
        {loading && <Spin style={{ display: 'block', margin: '8px auto' }} />}
        <div ref={endRef} />
      </div>
      <div style={{ padding: '12px 20px', borderTop: '1px solid #f0f0f0' }}>
        <div style={{ marginBottom: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {SUGGESTIONS.map(q => <Tag key={q} color="blue" style={{ cursor: 'pointer' }} onClick={() => send(q)}>{q}</Tag>)}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Input value={input} onChange={e => setInput(e.target.value)} onPressEnter={() => send()} placeholder="Ask the AI Agent..." />
          <Button type="primary" icon={<SendOutlined />} onClick={() => send()} loading={loading} />
        </div>
      </div>
    </Card>
  )
}

export default AskAnra
