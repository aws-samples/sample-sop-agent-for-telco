// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useState, useEffect, useRef, useCallback } from 'react'
import { Play, FileText, Edit, Eye, Loader2, CheckCircle, XCircle, Plus, AlertTriangle, Activity, ChevronLeft, ChevronRight, Maximize2, Upload } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar } from 'recharts'
import AgentStatusIndicator from './AgentStatusIndicator'
import ParticleBackground from './ParticleBackground'
import NetworkTopology from './NetworkTopology'
import AgentFlowDiagram from './AgentFlowDiagram'
import ExecutionHistory from './ExecutionHistory'
import AnimatedNumber from './AnimatedNumber'
import GitLabIssues from './GitLabIssues'

function App() {
  // Persist/restore helpers
  const loadState = (key, fallback) => {
    try { const v = localStorage.getItem(`nec_${key}`); return v ? JSON.parse(v) : fallback } catch { return fallback }
  }
  const saveState = (key, value) => { try { localStorage.setItem(`nec_${key}`, JSON.stringify(value)) } catch {} }

  const [sops, setSops] = useState([])
  const [selectedSop, setSelectedSop] = useState(null)
  const [sopContent, setSopContent] = useState('')
  const [mode, setMode] = useState('list') // list, view, edit
  const [executing, setExecuting] = useState(false)
  const [logs, setLogs] = useState(() => loadState('logs', []))
  const [agentStatus, setAgentStatus] = useState({
    status: 'idle',
    current_sop: null,
    start_time: null,
    end_time: null,
    last_output: null,
    progress: 0,
    eval_scores: {}
  })
  const [fixMode, setFixMode] = useState(false)
  const [evalMode, setEvalMode] = useState(false)
  const [autoCorrect, setAutoCorrect] = useState(false)
  const [evalResults, setEvalResults] = useState(() => loadState('evalResults', {}))
  const [model, setModel] = useState('opus4.6')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newSopName, setNewSopName] = useState('')
  const [uploadStatus, setUploadStatus] = useState(null) // null | 'uploading' | 'generating' | 'done' | 'error'
  const [uploadResult, setUploadResult] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const [metrics, setMetrics] = useState({ throughput: 0, latency: 0, packets: 0, cpu: 0, memory: 0 })
  const [alarms, setAlarms] = useState([])
  const [upfStats, setUpfStats] = useState({ ipackets: 0, opackets: 0, imissed: 0, dropRate: 0, fwdLoss: 0, totalLoss: 0, workerNG: 0 })
  const [alarmFilter, setAlarmFilter] = useState('all')
  const [executionSteps, setExecutionSteps] = useState(() => loadState('executionSteps', []))
  const [slidesExpanded, setSlidesExpanded] = useState(false)
  const [currentSlide, setCurrentSlide] = useState(1)
  const [diagramTab, setDiagramTab] = useState('network')
  const [loadingAlarms, setLoadingAlarms] = useState(true)
  const [loadingSops, setLoadingSops] = useState(true)
  const [loadingSopContent, setLoadingSopContent] = useState(false)
  const [graphData, setGraphData] = useState([])
  const [expandedGraph, setExpandedGraph] = useState(null)
  const [sessionData, setSessionData] = useState([])
  const [sopCache, setSopCache] = useState(new Map())
  const [sopQueue, setSopQueue] = useState([])
  const sopQueueRef = useRef([])
  const [graphNodes, setGraphNodes] = useState(() => loadState('graphNodes', {}))
  const graphNodesRef = useRef(graphNodes)
  useEffect(() => { graphNodesRef.current = graphNodes }, [graphNodes])
  const [evalTrends, setEvalTrends] = useState({}) // {sopStem: [{run_id, avg_score}]}
  const [execStats, setExecStats] = useState(() => loadState('execStats', {}))
  const [execStatsTab, setExecStatsTab] = useState('eval') // 'eval' | 'stats' | 'corrections'
  const [corrections, setCorrections] = useState(() => loadState('corrections', []))

  // Persist state changes to localStorage
  useEffect(() => { saveState('evalResults', evalResults) }, [evalResults])
  useEffect(() => { saveState('execStats', execStats) }, [execStats])
  useEffect(() => { saveState('executionSteps', executionSteps) }, [executionSteps])
  useEffect(() => { saveState('graphNodes', graphNodes) }, [graphNodes])
  useEffect(() => { saveState('logs', logs) }, [logs])
  useEffect(() => { saveState('corrections', corrections) }, [corrections])

  const clearSessionData = () => {
    setEvalResults({}); setExecStats({}); setExecutionSteps([]); setGraphNodes({})
    setLogs([]); setCorrections([]); setEvalTrends({})
    ;['evalResults','execStats','executionSteps','graphNodes','logs','corrections'].forEach(k => localStorage.removeItem(`nec_${k}`))
  }
  const totalSlides = 18
  const slidesContainerRef = useRef(null)
  const wsRef = useRef(null)
  const logsContainerRef = useRef(null)
  const executionContainerRef = useRef(null)

  useEffect(() => {
    fetchSops()
    fetchAlarms()
    fetchMetrics()
    fetchAgentStatus()
    // Load historical corrections if none in localStorage
    if (corrections.length === 0) {
      fetch('/api/corrections').then(r => r.json()).then(data => {
        if (data.length > 0) setCorrections(data)
      }).catch(() => {})
    }
    
    // Fetch real-time metrics every 2 seconds for live feel
    const metricsInterval = setInterval(() => {
      fetchMetrics()
    }, 2000)
    
    // Fetch alarms every 10 seconds without showing loading state
    const alarmsInterval = setInterval(() => {
      fetchAlarms(false)
    }, 10000)

    // Fetch agent status every 1 second for responsive tool highlighting
    const statusInterval = setInterval(() => {
      fetchAgentStatus()
    }, 1000)

    // Fetch App stats every 5 seconds
    const upfStatsInterval = setInterval(async () => {
      try { const r = await fetch('/api/app-stats'); setUpfStats(await r.json()) } catch {}
    }, 5000)
    
    return () => {
      clearInterval(metricsInterval)
      clearInterval(alarmsInterval)
      clearInterval(statusInterval)
      clearInterval(upfStatsInterval)
    }
  }, [])

  const fetchMetrics = async () => {
    try {
      const res = await fetch('/api/metrics')
      const data = await res.json()
      setMetrics(data)
      
      // Update graph data with real metrics
      const now = new Date()
      const timeStr = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      
      setGraphData(prev => {
        const newData = [...prev, {
          time: timeStr,
          rxGbps: data.rxGbps || 0,
          txGbps: data.txGbps || 0,
          combined: data.combined || 0,
          avgCpu: data.avgCpu || 0,
          maxCpu: data.maxCpu || 0,
          nodeCpu: data.nodeCpuPercent || 0
        }]
        // Keep last 5 minutes (150 data points at 2 second intervals)
        return newData.slice(-150)
      })
      
      setSessionData(prev => {
        const newData = [...prev, {
          time: timeStr,
          sessions: data.activeSessions || 0
        }]
        return newData.slice(-150)
      })
    } catch (err) {
      console.error('Failed to fetch metrics:', err)
    }
  }

  useEffect(() => {
    if (logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight
    }
  }, [logs])

  useEffect(() => {
    if (executionContainerRef.current) {
      executionContainerRef.current.scrollTop = executionContainerRef.current.scrollHeight
    }
  }, [executionSteps])

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (slidesExpanded) {
        if (e.key === 'ArrowLeft' && currentSlide > 1) {
          setCurrentSlide(prev => prev - 1)
        } else if (e.key === 'ArrowRight' && currentSlide < totalSlides) {
          setCurrentSlide(prev => prev + 1)
        } else if (e.key === 'Escape') {
          setSlidesExpanded(false)
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [slidesExpanded, currentSlide, totalSlides])

  const fetchAlarms = async (showLoading = true) => {
    if (showLoading) setLoadingAlarms(true)
    try {
      const res = await fetch('/api/alarms')
      const data = await res.json()
      setAlarms(data)
    } catch (err) {
      console.error('Failed to fetch alarms:', err)
    } finally {
      if (showLoading) setLoadingAlarms(false)
    }
  }

  const fetchSops = async () => {
    setLoadingSops(true)
    try {
      const res = await fetch('/api/sops')
      const data = await res.json()
      setSops(data)
      // Fetch eval trends for each SOP
      const trends = {}
      await Promise.all(data.map(async (sop) => {
        const stem = sop.name.replace('.md', '')
        try {
          const r = await fetch(`/api/eval-history/${stem}`)
          const hist = await r.json()
          if (hist.length) trends[stem] = hist.slice(0, 5)
        } catch {}
      }))
      setEvalTrends(trends)
    } catch (err) {
      console.error('Failed to fetch SOPs:', err)
    } finally {
      setLoadingSops(false)
    }
  }

  const fetchAgentStatus = async () => {
    try {
      const response = await fetch('/api/status')
      const data = await response.json()
      setAgentStatus(data)
      setExecuting(data.status === 'running')
      // Restore diagram nodes from execution steps (survives page refresh)
      if (data.steps?.length && Object.keys(graphNodesRef.current).length === 0) {
        const restored = {}
        for (const s of data.steps) {
          restored[s.name] = { status: s.status === 'success' ? 'success' : s.status === 'failed' ? 'failed' : 'running' }
        }
        setGraphNodes(restored)
      }
    } catch (error) {
      console.error('Error fetching agent status:', error)
    }
  }

  const loadSop = async (sop, e) => {
    if (e?.ctrlKey || e?.metaKey) {
      setSopQueue(prev => {
        const exists = prev.find(s => s.name === sop.name)
        const next = exists ? prev.filter(s => s.name !== sop.name) : [...prev, sop]
        sopQueueRef.current = next
        return next
      })
      return
    }
    setSopQueue([]); sopQueueRef.current = []
    setSelectedSop(sop)
    setMode('view')
    setSopContent('') // Clear previous content immediately
    setLoadingSopContent(true)
    
    try {
      const res = await fetch(`/api/sop/${sop.name}`)
      const data = await res.json()
      setSopContent(data.content)
    } catch (err) {
      console.error('Failed to load SOP:', err)
      setSopContent('Error loading SOP content')
    } finally {
      setLoadingSopContent(false)
    }
  }

  const saveSop = async () => {
    await fetch(`/api/sop/${selectedSop.name}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: selectedSop.path, content: sopContent })
    })
    setMode('view')
    fetchSops()
  }

  const createSop = async () => {
    if (!newSopName.trim()) return
    const res = await fetch('/api/sop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newSopName })
    })
    const data = await res.json()
    setShowCreateModal(false)
    setNewSopName('')
    await fetchSops()
    // Load the newly created SOP
    const newSop = {
      name: data.name,
      path: data.path,
      size: 0,
      modified: new Date().toISOString()
    }
    await loadSop(newSop)
    setMode('edit')
  }

  const openSlidesFullscreen = () => {
    setSlidesExpanded(true)
    setCurrentSlide(1)
    setTimeout(() => {
      if (slidesContainerRef.current) {
        if (slidesContainerRef.current.requestFullscreen) {
          slidesContainerRef.current.requestFullscreen()
        } else if (slidesContainerRef.current.webkitRequestFullscreen) {
          slidesContainerRef.current.webkitRequestFullscreen()
        } else if (slidesContainerRef.current.msRequestFullscreen) {
          slidesContainerRef.current.msRequestFullscreen()
        }
      }
    }, 100)
  }

  const handleDocUpload = useCallback(async (files) => {
    if (!files?.length) return
    const file = files[0]
    const allowed = ['.pdf', '.docx', '.md', '.txt', '.doc']
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase()
    if (!allowed.includes(ext)) {
      setUploadStatus('error')
      setUploadResult(`Unsupported file type: ${ext}. Use PDF, DOCX, MD, or TXT.`)
      return
    }
    setUploadStatus('uploading')
    setUploadResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      setUploadStatus('generating')
      const res = await fetch('/api/generate-sop', { method: 'POST', body: form })
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText)
      const data = await res.json()
      setUploadStatus('done')
      setUploadResult(`Generated: ${data.sop_name}`)
      await fetchSops()
      const newSop = { name: data.sop_name, path: data.path }
      await loadSop(newSop)
    } catch (err) {
      setUploadStatus('error')
      setUploadResult(err.message)
    }
  }, [])

  const getAlarmColor = (priority) => {
    switch(priority) {
      case 'critical': return 'text-red-400 bg-red-900/30'
      case 'warning': return 'text-yellow-400 bg-yellow-900/30'
      case 'info': return 'text-blue-400 bg-blue-900/30'
      default: return 'text-gray-400 bg-gray-900/30'
    }
  }

  const filteredAlarms = alarmFilter === 'all' 
    ? alarms 
    : alarms.filter(a => a.priority === alarmFilter)

  const executeGraph = (queue) => {
    if (!queue || queue.length === 0) return
    setExecuting(true)
    setLogs([])
    setExecutionSteps([])
    setEvalResults({})
    setExecStats({})
    setGraphNodes({})

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws/execute-graph`)
    wsRef.current = ws

    ws.onopen = () => {
      ws.send(JSON.stringify({
        sop_paths: queue.map(s => s.path),
        fix_mode: fixMode,
        model: model,
        eval_mode: evalMode,
        auto_correct: autoCorrect,
      }))
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        setLogs(prev => [...prev, data])

        if (data.type === 'node_start') {
          setExecutionSteps(prev => [...prev, { name: `▶ ${data.node_id}`, status: 'running' }])
          setGraphNodes(prev => ({ ...prev, [data.node_id]: { status: 'running' } }))
        } else if (data.type === 'node_complete') {
          const status = data.status === 'completed' ? 'success' : 'failed'
          const time = data.execution_time_ms ? ` (${(data.execution_time_ms / 1000).toFixed(1)}s)` : ''
          setExecutionSteps(prev => {
            const updated = [...prev]
            // Resolve ALL remaining running steps for this node (tool calls that never got a result)
            for (let i = 0; i < updated.length; i++) {
              if (updated[i].status === 'running' && (updated[i].name.includes(data.node_id) || updated[i].name.startsWith(`[${data.node_id}]`))) {
                updated[i] = { ...updated[i], status }
              }
            }
            // Update or add the node-level step
            let found = false
            for (let i = updated.length - 1; i >= 0; i--) {
              if (updated[i].name.includes(`▶ ${data.node_id}`) || updated[i].name === data.node_id) {
                updated[i] = { name: `${data.node_id}${time}`, status }
                found = true
                break
              }
            }
            if (!found) updated.push({ name: `${data.node_id}${time}`, status })
            return updated
          })
          setGraphNodes(prev => ({ ...prev, [data.node_id]: { status, time_ms: data.execution_time_ms } }))
          // Track execution stats per node
          if (!data.node_id.startsWith('eval') && !data.node_id.startsWith('correct')) {
            setExecStats(prev => ({
              ...prev,
              [data.node_id]: {
                ...(prev[data.node_id] || {}),
                inputTokens: data.token_usage?.inputTokens || 0,
                outputTokens: data.token_usage?.outputTokens || 0,
                time_ms: data.execution_time_ms || 0,
              }
            }))
          }
          // Track corrections
          if (data.node_id.startsWith('correct-')) {
            const sop = data.node_id.replace('correct-', '')
            setCorrections(prev => [...prev, {
              sop,
              status: data.status,
              time: new Date().toISOString(),
              output: data.output_summary || '',
            }])
          }
        } else if (data.type === 'graph_complete') {
          const summary = `Graph: ${data.completed_nodes} completed, ${data.failed_nodes} failed (${(data.execution_time_ms / 1000).toFixed(1)}s)`
          setExecutionSteps(prev => [...prev, { name: summary, status: 'summary' }])
          // Resolve any eval nodes that received scores but missed node_complete
          setGraphNodes(prev => {
            const updated = { ...prev }
            for (const [id, node] of Object.entries(updated)) {
              if (!node.status && node.scores) {
                updated[id] = { ...node, status: node.avgScore >= 0.5 ? 'success' : 'failed' }
              }
            }
            return updated
          })
        } else if (data.type === 'output' && data.message) {
          const msg = data.message.replace(/\[[0-9;]*m/g, '')
          const nid = data.node_id || ''
          const isEvalNode = nid.startsWith('eval') || nid.startsWith('correct')

          // Tool call started
          if (data.tool_call) {
            // Increment tool count for this node
            if (nid && !isEvalNode) {
              setExecStats(prev => ({
                ...prev,
                [nid]: { ...(prev[nid] || {}), tools: ((prev[nid] || {}).tools || 0) + 1 }
              }))
            }
            if (!isEvalNode) {
              const toolNames = { 'kubectl': 'Kubernetes', 'kubectl_exec': 'Pod Command', 'check_pod_status': 'Pod Health', 'get_pod_name': 'Find Pod', 'read_sop': 'Read SOP', 'parse_sop': 'Parse SOP', 'argocd_status': 'ArgoCD Status', 'argocd_sync': 'ArgoCD Sync', 'describe_node': 'Node Info', 'get_pod_logs': 'Pod Logs', 'telcocli': 'TelcoCLI', 'ssh_command': 'SSH', 'ssh_expect': 'SSH Interactive' }
              const tool = data.tool_call.tool
              setExecutionSteps(prev => [...prev, { name: `[${nid}] ${toolNames[tool] || tool}`, status: 'running' }])
            }
          } else if (!isEvalNode && msg.includes('└─')) {
            setExecutionSteps(prev => {
              const updated = [...prev]
              for (let i = updated.length - 1; i >= 0; i--) {
                if (updated[i].status === 'running' && updated[i].name.startsWith(`[${nid}]`)) {
                  updated[i] = { ...updated[i], status: (msg.includes('OK') || msg.includes('Exit 0') || msg.includes('Read ') || msg.includes('Pod:') || msg.includes('Found ')) ? 'success' : 'failed' }
                  break
                }
              }
              return updated
            })
          } else if (!isEvalNode && msg.includes('✅') && msg.includes('PASS')) {
            const desc = msg.replace(/[*✅]/g, '').replace('PASS:', '').replace(/\[.*?\]\s*/, '').trim().substring(0, 100)
            setExecutionSteps(prev => [...prev, { name: `[${nid}] ${desc}`, status: 'success' }])
          } else if (!isEvalNode && msg.includes('❌') && (msg.includes('FAIL') || msg.includes('FAILURE'))) {
            const desc = msg.replace(/[*❌]/g, '').replace(/CRITICAL\s+/,'').replace('FAILURE:', '').replace('FAIL:', '').replace(/\[.*?\]\s*/, '').trim().substring(0, 100)
            setExecutionSteps(prev => [...prev, { name: `[${nid}] ${desc}`, status: 'failed' }])
          }

          // Eval scores
          if (data.eval_score) {
            const sopName = data.eval_score.node_id || nid || 'graph'
            // Skip 'unknown' evaluator names — noise from SOP node output parsing
            if (data.eval_score.name && data.eval_score.name !== 'unknown') {
              setEvalResults(prev => ({
                ...prev,
                [sopName]: { ...(prev[sopName] || {}), [data.eval_score.name]: data.eval_score.score }
              }))
              setAgentStatus(prev => ({
                ...prev,
                eval_scores: { ...prev.eval_scores, [data.eval_score.name]: data.eval_score.score }
              }))
              // Store score in graphNodes so the diagram can display it
              setGraphNodes(prev => {
                const evalNodeId = sopName.startsWith('eval-') ? sopName : `eval-${sopName.replace('eval-', '')}`
                const existing = prev[evalNodeId] || {}
                const scores = { ...(existing.scores || {}), [data.eval_score.name]: data.eval_score.score }
                const avg = Object.values(scores).reduce((a, b) => a + b, 0) / Object.values(scores).length
                return { ...prev, [evalNodeId]: { ...existing, scores, avgScore: avg } }
              })
            }
          }
        }

        if (data.type === 'complete' || data.type === 'error') {
          setExecuting(false)
          setSopQueue([]); sopQueueRef.current = []
          ws.close()
        }
      } catch (err) {}
    }

    ws.onerror = () => {}  // Status polling handles executing state
    ws.onclose = () => {}  // Execution continues in background; /api/status polling updates UI
  }

  const getLogColor = (log) => {
    if (log.message?.includes('✅') || log.message?.includes('PASS')) return 'text-green-400'
    if (log.message?.includes('❌') || log.message?.includes('FAILURE')) return 'text-red-400'
    if (log.message?.includes('🔧') || log.message?.includes('TOOL')) return 'text-cyan-400'
    if (log.type === 'error') return 'text-red-400'
    return 'text-gray-300'
  }

  const getStepIcon = (status) => {
    if (status === 'success') return <CheckCircle size={16} className="text-green-400" />
    if (status === 'failed') return <XCircle size={16} className="text-red-400" />
    if (status === 'summary') return <FileText size={16} className="text-purple-400" />
    return <Loader2 size={16} className="text-blue-400 animate-spin" />
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0a0e1a] via-[#0d1526] to-[#111827] relative overflow-hidden">
      {/* Animated particle network background */}
      <ParticleBackground />
      
      <div className="container mx-auto px-4 py-8 relative z-10">
        <header className="mb-6 backdrop-blur-sm bg-white/5 rounded-2xl p-5 border border-white/10 shadow-2xl">
          <div className="text-center">
            <h1 className="text-4xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-[#FF9900] via-[#FFB84D] to-[#00A4A6] mb-2 animate-gradient">
              SOP Agent for Strands
            </h1>
            <p className="text-blue-300 text-sm flex items-center justify-center gap-2 mt-1">
              <span className="px-2.5 py-0.5 rounded-full bg-purple-500/20 border border-purple-500/40 text-purple-300 text-xs font-semibold">Strands SDK</span>
              <span className="text-gray-500">+</span>
              <span className="px-2.5 py-0.5 rounded-full bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 text-xs font-semibold">Amazon Bedrock</span>
            </p>
          </div>
        </header>

        {/* Agent Status Indicator */}
        <AgentStatusIndicator agentStatus={agentStatus} model={model} />

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Left Column - SOPs & Chat */}
          <div className="space-y-6">
            {/* SOP List */}
            <div className="bg-gray-800/80 backdrop-blur-md rounded-2xl shadow-2xl p-5 border border-gray-700/50 hover:border-blue-500/50 transition-all duration-300">
              <div className="flex justify-between items-center mb-3">
                <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                  <span className="text-xl">📋</span>
                  Standard Operating Procedures (SOP's)
                </h2>
                {sopQueue.length > 0 && <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/40 font-semibold">{sopQueue.length} queued</span>}
                <button
                  onClick={() => setShowCreateModal(true)}
                  className="p-2 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-500 hover:to-emerald-500 text-white rounded-lg shadow-lg hover:shadow-green-500/50 transition-all duration-300 transform hover:scale-105"
                  title="Create New SOP"
                >
                  <Plus size={18} />
                </button>
              </div>
              <div className="space-y-2 max-h-72 overflow-y-auto">
                {loadingSops ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="animate-spin text-blue-400" size={24} />
                    <span className="ml-2 text-gray-400">Loading SOPs...</span>
                  </div>
                ) : sops.length === 0 ? (
                  <div className="text-center py-8 text-gray-400">No SOPs found</div>
                ) : (
                  sops.map((sop, idx) => (
                    <div
                      key={sop.name}
                      onClick={(e) => loadSop(sop, e)}
                      className={`p-2.5 rounded-xl cursor-pointer transition-all duration-300 transform hover:scale-102 ${
                        sopQueue.find(s => s.name === sop.name)
                          ? 'bg-gradient-to-r from-purple-900/80 to-pink-900/80 text-white shadow-lg shadow-purple-500/50 ring-2 ring-purple-400/60'
                          : selectedSop?.name === sop.name
                          ? 'bg-gradient-to-r from-blue-600 to-purple-600 text-white shadow-lg shadow-blue-500/50'
                          : 'bg-gray-700/50 text-gray-200 hover:bg-gray-600/70 hover:shadow-md'
                      }`}
                    >
                      <div className="font-medium text-sm flex items-center gap-2">
                        <span className="text-xs opacity-75">{idx + 1}.</span>
                        <span className="flex-1">{sop.name.replace('.md', '').replace(/^\d+-/, '').replace(/-/g, ' ').replace(/\w/g, c => c.toUpperCase())}</span>
                        {sopQueue.find(s => s.name === sop.name) && (
                          <span className="bg-purple-900/40 border border-purple-500/30 rounded-md px-1.5 py-0.5 text-purple-300 text-[10px] font-semibold">
                            {sopQueue.findIndex(s => s.name === sop.name) + 1}
                          </span>
                        )}
                        {agentStatus.history?.[sop.name] ? (
                          <div className="flex items-center gap-1">
                            {agentStatus.history[sop.name].start_time && agentStatus.history[sop.name].end_time && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-600/30 text-gray-400 border border-gray-600/40 font-semibold">
                                {(() => { const s = Math.round((new Date(agentStatus.history[sop.name].end_time) - new Date(agentStatus.history[sop.name].start_time)) / 1000); return `${Math.floor(s/3600)}:${String(Math.floor((s%3600)/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}` })()}
                              </span>
                            )}
                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${
                              agentStatus.history[sop.name].status === 'completed'
                                ? 'bg-green-500/20 text-green-300 border border-green-500/40'
                                : 'bg-red-500/20 text-red-300 border border-red-500/40'
                            }`}>
                              {agentStatus.history[sop.name].status === 'completed' ? '✓ Pass' : '✗ Fail'}
                            </span>
                          </div>
                        ) : (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-600/30 text-gray-500 border border-gray-600/40 font-semibold">—</span>
                        )}
                        {/* Eval score trend — shows last N run scores with tooltip */}
                        {(() => {
                          const stem = sop.name.replace('.md', '')
                          const trend = evalTrends[stem]
                          if (!trend || trend.length < 2) return null
                          const scores = trend.map(t => t.avg_score).reverse()
                          const last = scores[scores.length - 1]
                          const avg = (scores.reduce((a, b) => a + b, 0) / scores.length * 100).toFixed(0)
                          const color = last >= 0.8 ? '#22c55e' : last >= 0.5 ? '#fbbf24' : '#ef4444'
                          const w = 36, h = 14, pad = 1
                          const pts = scores.map((s, i) => `${pad + i * ((w - 2*pad) / Math.max(scores.length - 1, 1))},${pad + (1 - s) * (h - 2*pad)}`).join(' ')
                          return (
                            <span className="inline-flex items-center gap-0.5" title={`Eval trend: ${scores.length} runs, avg ${avg}%`}>
                              <svg width={w} height={h} className="opacity-70">
                                <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                              <span className="text-[9px] opacity-50" style={{color}}>{avg}%</span>
                            </span>
                          )
                        })()}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Diagram Tabs: Network / Agent Flow */}
            <div>
              <div className="flex gap-1 mb-2">
                <button onClick={() => setDiagramTab('network')} className={`px-3 py-1 rounded-t-lg text-xs font-semibold transition-all ${diagramTab === 'network' ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 border-b-0' : 'text-gray-500 hover:text-gray-300'}`}>Network</button>
                <button onClick={() => setDiagramTab('agent')} className={`px-3 py-1 rounded-t-lg text-xs font-semibold transition-all ${diagramTab === 'agent' ? 'bg-purple-500/30 text-purple-200 border border-purple-400/60 border-b-0' : 'text-gray-500 hover:text-gray-300'}`}>Agent Flow</button>
                <button onClick={() => setDiagramTab('history')} className={`px-3 py-1 rounded-t-lg text-xs font-semibold transition-all ${diagramTab === 'history' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 border-b-0' : 'text-gray-500 hover:text-gray-300'}`}>History</button>
              </div>
              {diagramTab === 'network' ? <NetworkTopology /> : diagramTab === 'agent' ? <AgentFlowDiagram agentStatus={agentStatus} graphNodes={graphNodes} /> : <ExecutionHistory />}
            </div>

            {/* Document Upload → SOP Generation */}
            <div className="bg-gray-800/80 backdrop-blur-md rounded-2xl shadow-2xl p-5 border border-gray-700/50 hover:border-emerald-500/50 transition-all duration-300">
              <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-3">
                <Upload size={20} className="text-emerald-400" />
                Document → SOP
              </h2>
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => { e.preventDefault(); setDragOver(false); handleDocUpload(e.dataTransfer.files) }}
                onClick={() => { const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.pdf,.docx,.doc,.md,.txt'; inp.onchange = (e) => handleDocUpload(e.target.files); inp.click() }}
                className={`rounded-xl border-2 border-dashed p-6 text-center cursor-pointer transition-all duration-300 ${
                  dragOver ? 'border-emerald-400 bg-emerald-900/30' : 'border-gray-600 bg-gray-900/50 hover:border-emerald-500/50 hover:bg-gray-900/70'
                }`}
              >
                {uploadStatus === 'uploading' || uploadStatus === 'generating' ? (
                  <div className="flex flex-col items-center gap-2">
                    <Loader2 size={28} className="animate-spin text-emerald-400" />
                    <span className="text-emerald-300 text-sm">{uploadStatus === 'uploading' ? 'Uploading...' : 'Generating SOP via Strands Agent...'}</span>
                  </div>
                ) : (
                  <>
                    <Upload size={28} className="mx-auto mb-2 text-gray-500" />
                    <p className="text-gray-400 text-sm">Drop HLD, LLD, or Run-books here</p>
                    <p className="text-gray-600 text-xs mt-1">PDF, DOCX, MD, TXT</p>
                  </>
                )}
              </div>
              {uploadResult && (
                <div className={`mt-2 text-xs px-3 py-2 rounded-lg ${uploadStatus === 'done' ? 'bg-emerald-900/30 text-emerald-300 border border-emerald-500/30' : 'bg-red-900/30 text-red-300 border border-red-500/30'}`}>
                  {uploadResult}
                </div>
              )}
            </div>
          </div>

          {/* Center Column - SOP Content */}
          <div className="lg:col-span-2 bg-gray-800/80 backdrop-blur-md rounded-2xl shadow-2xl p-6 border border-gray-700/50 hover:border-blue-500/50 transition-all duration-300">
            {selectedSop ? (
              <>
                <div className="mb-6">
                  <h2 className="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400 mb-2">
                    SOP Editor
                  </h2>
                  <div className="flex justify-between items-center">
                    <div className="text-gray-400 text-sm flex items-center gap-2">
                      <FileText size={16} className="text-blue-400" />
                      {selectedSop.name}
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setMode('view')}
                        className={`p-2 rounded-lg transition-all duration-300 ${
                          mode === 'view' 
                            ? 'bg-gradient-to-r from-blue-600 to-blue-500 text-white shadow-lg shadow-blue-500/50' 
                            : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                        }`}
                        title="View Mode"
                      >
                        <Eye size={20} />
                      </button>
                      <button
                        onClick={() => setMode('edit')}
                        className={`p-2 rounded-lg transition-all duration-300 ${
                          mode === 'edit' 
                            ? 'bg-gradient-to-r from-purple-600 to-purple-500 text-white shadow-lg shadow-purple-500/50' 
                            : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                        }`}
                        title="Edit Mode"
                      >
                        <Edit size={20} />
                      </button>
                      <button
                        onClick={() => { if (window.confirm(`Delete ${selectedSop.name}?`)) { fetch(`/api/sop/${selectedSop.name}`, {method:'DELETE'}).then(r => { if(r.ok) { setSops(prev => prev.filter(s => s.name !== selectedSop.name)); setSopQueue(prev => { const next = prev.filter(s => s.name !== selectedSop.name); sopQueueRef.current = next; return next }); setSelectedSop(null); setSopContent('') } }) } }}
                        className="p-2 rounded-lg bg-gray-700 text-gray-300 hover:bg-red-600/80 hover:text-white transition-all duration-300"
                        title="Delete SOP"
                      >
                        <XCircle size={20} />
                      </button>
                    </div>
                  </div>
                </div>

                {mode === 'edit' ? (
                  <>
                    <textarea
                      value={sopContent}
                      onChange={(e) => setSopContent(e.target.value)}
                      spellCheck={false}
                      className={`w-full bg-gradient-to-br from-gray-900/90 to-blue-900/30 text-gray-200 p-4 rounded-xl font-mono text-sm border border-blue-500/30 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/50 transition-all outline-none ${
                        executing ? 'h-48' : 'h-80'
                      }`}
                    />
                    <button
                      onClick={saveSop}
                      className="mt-4 px-6 py-2 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-500 hover:to-emerald-500 text-white rounded-lg shadow-lg hover:shadow-green-500/50 transition-all duration-300 transform hover:scale-105"
                    >
                      💾 Save Changes
                    </button>
                  </>
                ) : (
                  <div className={`bg-gradient-to-br from-gray-900/90 to-blue-900/30 p-4 rounded-xl overflow-y-auto border border-blue-500/20 transition-all duration-300 ${
                    executing ? 'h-48' : 'h-80'
                  }`}>
                    {loadingSopContent ? (
                      <div className="flex items-center justify-center h-full">
                        <Loader2 className="animate-spin text-blue-400" size={32} />
                        <span className="ml-3 text-gray-400">Loading SOP content...</span>
                      </div>
                    ) : (
                      <pre className="text-gray-200 text-sm whitespace-pre-wrap">{sopContent}</pre>
                    )}
                  </div>
                )}

                {/* Execution Controls */}
                <div className="mt-4 p-2 bg-gradient-to-r from-gray-700/80 to-gray-600/80 rounded-xl border border-gray-600/50">
                  <div className="flex items-center gap-3">
                    <label className="flex items-center text-gray-300 text-xs whitespace-nowrap">
                      <input
                        type="radio"
                        name="execMode"
                        checked={!fixMode}
                        onChange={() => setFixMode(false)}
                        className="mr-1 accent-blue-600"
                        disabled={executing}
                      />
                      Validate
                    </label>
                    <label className="flex items-center text-gray-300 text-xs whitespace-nowrap">
                      <input
                        type="radio"
                        name="execMode"
                        checked={fixMode}
                        onChange={() => setFixMode(true)}
                        className="mr-1 accent-purple-600"
                        disabled={executing}
                      />
                      Fix
                    </label>
                    <div className="flex items-center gap-2 ml-2 border-l border-gray-700 pl-2">
                      <label className="flex items-center text-gray-300 text-xs whitespace-nowrap">
                        <input
                          type="checkbox"
                          checked={evalMode}
                          onChange={(e) => { setEvalMode(e.target.checked); if (!e.target.checked) setAutoCorrect(false); }}
                          className="mr-1 accent-green-600"
                          disabled={executing}
                        />
                        Evaluate
                      </label>
                      <label className={`flex items-center text-xs whitespace-nowrap ${evalMode ? 'text-gray-300' : 'text-gray-600'}`}>
                        <input
                          type="checkbox"
                          checked={autoCorrect}
                          onChange={(e) => setAutoCorrect(e.target.checked)}
                          className="mr-1 accent-yellow-600"
                          disabled={executing || !evalMode}
                        />
                        Auto-Correct
                      </label>
                    </div>
                    <div className="flex-1" />
                    <button
                      onClick={() => {
                        const queue = sopQueue.length > 0 ? sopQueue : (selectedSop ? [selectedSop] : [])
                        if (queue.length > 0) executeGraph(queue)
                      }}
                      disabled={executing || (!selectedSop && sopQueue.length === 0)}
                      className="px-3 py-1.5 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 disabled:from-gray-600 disabled:to-gray-600 text-white rounded-lg font-semibold flex items-center gap-1.5 text-xs whitespace-nowrap shadow-lg hover:shadow-blue-500/50 transition-all duration-300 transform hover:scale-105 disabled:transform-none"
                    >
                      {executing ? (
                        <>
                          <Loader2 className="animate-spin" size={14} />
                          Executing...
                        </>
                      ) : (
                        <>
                          <Play size={14} />
                          {sopQueue.length > 1 ? `Run ${sopQueue.length} SOPs` : 'Execute'}
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {/* Execution Progress */}
                {executionSteps.length > 0 && (
                  <div className="mt-4">
                    <h3 className="text-white font-semibold mb-3 text-sm flex items-center gap-2">
                      <Activity size={16} className="text-blue-400 animate-pulse" />
                      Execution Progress
                      <span className="ml-auto text-xs text-gray-400">
                        {executionSteps.filter(s => s.status === 'success').length} passed, {executionSteps.filter(s => s.status === 'failed').length} failed
                      </span>
                    </h3>
                    <div ref={executionContainerRef} className="bg-gradient-to-br from-gray-900/90 to-blue-900/30 rounded-xl p-3 space-y-2 border border-blue-500/20 max-h-[420px] overflow-y-auto">
                      {executionSteps.map((step, i) => (
                        <div key={i} className={`flex items-start gap-3 p-3 rounded-lg transition-all duration-300 ${
                          step.status === 'success' ? 'bg-green-900/20 border border-green-500/40' :
                          step.status === 'failed' ? 'bg-red-900/20 border border-red-500/40' :
                          step.status === 'summary' ? 'bg-purple-900/30 border border-purple-500/50' :
                          'bg-blue-900/20 border border-blue-500/40 animate-pulse'
                        }`}>
                          <div className="mt-0.5">
                            {getStepIcon(step.status)}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className={`text-sm font-medium whitespace-pre-wrap ${
                              step.status === 'success' ? 'text-green-300' :
                              step.status === 'failed' ? 'text-red-300' : 
                              step.status === 'summary' ? 'text-purple-300' : 'text-blue-300'
                            }`}>
                              {step.name}
                            </div>
                          </div>
                          {step.status !== 'summary' && (
                            <span className={`text-xs px-2.5 py-1 rounded-full font-semibold whitespace-nowrap ${
                              step.status === 'success' ? 'bg-green-500/30 text-green-300 border border-green-500/50' :
                              step.status === 'failed' ? 'bg-red-500/30 text-red-300 border border-red-500/50' : 
                              'bg-blue-500/30 text-blue-300 border border-blue-500/50'
                            }`}>
                              {step.status === 'success' ? '✓ Pass' : step.status === 'failed' ? '✗ Fail' : '⟳ Running'}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Eval / Stats Tabs */}
                {(Object.keys(evalResults).length > 0 || Object.keys(execStats).length > 0 || corrections.length > 0) && (
                  <div className="mt-4">
                    <div className="flex gap-1 mb-2 items-center">
                      <button onClick={() => setExecStatsTab('eval')} className={`px-3 py-1 rounded-t-lg text-xs font-semibold transition-all ${execStatsTab === 'eval' ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40 border-b-0' : 'text-gray-500 hover:text-gray-300'}`}>🧪 Eval Scores</button>
                      <button onClick={() => setExecStatsTab('stats')} className={`px-3 py-1 rounded-t-lg text-xs font-semibold transition-all ${execStatsTab === 'stats' ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 border-b-0' : 'text-gray-500 hover:text-gray-300'}`}>📊 Execution Stats</button>
                      <button onClick={() => setExecStatsTab('corrections')} className={`px-3 py-1 rounded-t-lg text-xs font-semibold transition-all ${execStatsTab === 'corrections' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 border-b-0' : 'text-gray-500 hover:text-gray-300'}`}>
                        🔧 Corrections{corrections.length > 0 && <span className="ml-1 bg-amber-500/30 text-amber-300 px-1.5 rounded-full">{corrections.length}</span>}
                      </button>
                      <button onClick={() => { if (window.confirm('Clear all session data?')) clearSessionData() }} className="ml-auto px-2 py-1 text-xs text-gray-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-all" title="Clear all session data">🗑 Clear</button>
                    </div>

                    {execStatsTab === 'eval' && Object.keys(evalResults).length > 0 && (
                    <div className="bg-gradient-to-br from-gray-900/90 to-purple-900/20 rounded-xl border border-purple-500/30 overflow-hidden">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-purple-500/20">
                            <th className="text-left text-purple-300 font-semibold p-2.5">SOP</th>
                            {(() => {
                              const allEvals = new Set()
                              const evalTooltips = {
                                'SteeringEffectiveness': '1.0 = no wasted tool calls. Deducts for repeated failures (same error 3+ times) and tool budget overrun (>80 warn, >95 fail).',
                                'SOPCompletion': '1.0 = all required tools called, no failure markers. Deducts 0.3 per issue: missing tools, ❌ FAILURE in output, or empty output.',
                              }
                              Object.values(evalResults).forEach(scores => Object.keys(scores).forEach(k => allEvals.add(k)))
                              return [...allEvals].map(name => {
                                const short = name.replace('Evaluator', '').replace('Effectiveness', 'Eff.').replace('Completion', 'Compl.')
                                const tipKey = name.replace('Evaluator', '')
                                return (
                                <th key={name} className="text-center text-purple-300 font-semibold p-2.5">
                                  <span className="inline-flex items-center gap-1">
                                    {short}
                                    <span title={evalTooltips[tipKey] || name} className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-purple-400/50 text-purple-400/70 text-[9px] cursor-help hover:border-purple-300 hover:text-purple-300">?</span>
                                  </span>
                                </th>
                              )})
                            })()}
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(evalResults).map(([sopName, scores]) => (
                            <tr key={sopName} className="border-b border-gray-700/30 hover:bg-purple-500/5">
                              <td className="p-2.5 text-gray-300 font-medium">{sopName.replace('.md', '')}</td>
                              {(() => {
                                const allEvals = new Set()
                                Object.values(evalResults).forEach(s => Object.keys(s).forEach(k => allEvals.add(k)))
                                return [...allEvals].map(name => {
                                  const score = scores[name]
                                  const color = score >= 0.8 ? 'text-green-400' : score >= 0.5 ? 'text-yellow-400' : 'text-red-400'
                                  const bg = score >= 0.8 ? 'bg-green-500/20' : score >= 0.5 ? 'bg-yellow-500/20' : 'bg-red-500/20'
                                  return (
                                    <td key={name} className="p-2.5 text-center">
                                      {score != null ? (
                                        <span className={`${color} ${bg} px-2.5 py-1 rounded-full font-bold`}>
                                          {score.toFixed(2)}
                                        </span>
                                      ) : <span className="text-gray-600">—</span>}
                                    </td>
                                  )
                                })
                              })()}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    )}

                    {execStatsTab === 'stats' && Object.keys(execStats).length > 0 && (() => {
                      const INPUT_PRICE = 3.0 / 1_000_000
                      const OUTPUT_PRICE = 15.0 / 1_000_000
                      const totals = Object.values(execStats).reduce((acc, s) => ({
                        inputTokens: acc.inputTokens + (s.inputTokens || 0),
                        outputTokens: acc.outputTokens + (s.outputTokens || 0),
                        tools: acc.tools + (s.tools || 0),
                        time_ms: acc.time_ms + (s.time_ms || 0),
                      }), { inputTokens: 0, outputTokens: 0, tools: 0, time_ms: 0 })
                      const totalCost = totals.inputTokens * INPUT_PRICE + totals.outputTokens * OUTPUT_PRICE
                      const fmt = n => n >= 1_000_000 ? `${(n/1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n/1_000).toFixed(0)}K` : n
                      return (
                        <div className="bg-gradient-to-br from-gray-900/90 to-cyan-900/20 rounded-xl border border-cyan-500/30 overflow-hidden">
                          {/* Summary bar */}
                          <div className="flex gap-4 p-3 border-b border-cyan-500/20 text-xs">
                            <div className="flex items-center gap-1.5"><span className="text-cyan-400">🔧</span><span className="text-gray-400">Tools</span><span className="text-white font-bold">{totals.tools}</span></div>
                            <div className="flex items-center gap-1.5"><span className="text-cyan-400">📝</span><span className="text-gray-400">Input</span><span className="text-white font-bold">{fmt(totals.inputTokens)}</span></div>
                            <div className="flex items-center gap-1.5"><span className="text-cyan-400">📤</span><span className="text-gray-400">Output</span><span className="text-white font-bold">{fmt(totals.outputTokens)}</span></div>
                            <div className="flex items-center gap-1.5"><span className="text-cyan-400">⏱</span><span className="text-gray-400">Time</span><span className="text-white font-bold">{(totals.time_ms / 1000 / 60).toFixed(1)}m</span></div>
                            <div className="flex items-center gap-1.5 ml-auto"><span className="text-green-400 text-sm font-bold">${totalCost.toFixed(2)}</span><span className="text-gray-500">Bedrock</span></div>
                          </div>
                          {/* Per-node table */}
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-cyan-500/20">
                                <th className="text-left text-cyan-300 font-semibold p-2.5">SOP</th>
                                <th className="text-center text-cyan-300 font-semibold p-2.5">Tools</th>
                                <th className="text-center text-cyan-300 font-semibold p-2.5">Input</th>
                                <th className="text-center text-cyan-300 font-semibold p-2.5">Output</th>
                                <th className="text-center text-cyan-300 font-semibold p-2.5">Time</th>
                                <th className="text-right text-cyan-300 font-semibold p-2.5">Cost</th>
                              </tr>
                            </thead>
                            <tbody>
                              {Object.entries(execStats).map(([nodeId, s]) => {
                                const cost = (s.inputTokens || 0) * INPUT_PRICE + (s.outputTokens || 0) * OUTPUT_PRICE
                                return (
                                  <tr key={nodeId} className="border-b border-gray-700/30 hover:bg-cyan-500/5">
                                    <td className="p-2.5 text-gray-300 font-medium">{nodeId}</td>
                                    <td className="p-2.5 text-center text-gray-300">{s.tools || 0}</td>
                                    <td className="p-2.5 text-center text-gray-300">{fmt(s.inputTokens || 0)}</td>
                                    <td className="p-2.5 text-center text-gray-300">{fmt(s.outputTokens || 0)}</td>
                                    <td className="p-2.5 text-center text-gray-300">{((s.time_ms || 0) / 1000).toFixed(0)}s</td>
                                    <td className="p-2.5 text-right text-green-400 font-bold">${cost.toFixed(2)}</td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                        </div>
                      )
                    })()}

                    {execStatsTab === 'corrections' && (
                      <div className="bg-gradient-to-br from-gray-900/90 to-amber-900/20 rounded-xl border border-amber-500/30 overflow-hidden">
                        {corrections.length === 0 ? (
                          <div className="p-6 text-center text-gray-500 text-sm">No corrections yet. Enable <span className="text-amber-300">Auto-Correct</span> to see the self-improvement loop in action.</div>
                        ) : (
                          <div className="divide-y divide-amber-500/10">
                            {corrections.map((c, i) => {
                              const lines = (c.output || '').replace(/^\[?\{?'text':\s*'?/,'').replace(/'?\}?\]?$/,'').split('\n').filter(l => l.trim())
                              const title = lines.find(l => l.includes('Fixed:') || l.includes('patched')) || lines[0] || 'Correction applied'
                              const details = lines.filter(l => l !== title && !l.startsWith('['))
                              return (
                                <div key={i} className="p-3">
                                  <div className="flex items-center gap-2 mb-1">
                                    <span className="text-amber-400 font-bold text-xs">🔧 {c.sop}</span>
                                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${c.status === 'completed' || c.status === 'success' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>{c.status === 'completed' || c.status === 'success' ? 'patched' : c.status}</span>
                                    {c.run_id && <span className="text-[10px] text-gray-600 ml-auto">Run {c.run_id}</span>}
                                  </div>
                                  <div className="text-xs text-gray-300 mb-1">{title}</div>
                                  {details.length > 0 && (
                                    <div className="text-[11px] text-gray-500 bg-black/30 rounded p-2 mt-1 font-mono">
                                      {details.map((line, j) => <div key={j}>{line}</div>)}
                                    </div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Execution Logs */}
                {logs.length > 0 && (
                  <div className="mt-4">
                    <h3 className="text-white font-semibold mb-3 text-sm">📋 Execution Logs</h3>
                    <div ref={logsContainerRef} className="bg-black rounded p-4 h-64 overflow-y-auto font-mono text-xs">
                      {logs.map((log, i) => (
                        <div key={i} className={getLogColor(log)}>
                          {log.message || JSON.stringify(log)}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="flex items-center justify-center h-96 text-gray-400">
                <div className="text-center">
                  <FileText size={64} className="mx-auto mb-4 opacity-50" />
                  <p>Select an SOP to get started</p>
                </div>
              </div>
            )}
          </div>

          {/* Right Column - Metrics & Alarms */}
          <div className="space-y-6">
            {/* Real-time Graphs */}
            <div className="bg-gray-800/80 backdrop-blur-md rounded-2xl shadow-2xl p-6 border border-gray-700/50 hover:border-green-500/50 transition-all duration-300">
              <h2 className="text-xl font-semibold text-white mb-4 flex items-center gap-2">
                <Activity size={24} className="text-green-400 animate-pulse" />
                Live Metrics
              </h2>
              
              {/* Combined Throughput KPI - HERO SIZE */}
              <div className="mb-4 bg-gradient-to-br from-green-900/50 to-emerald-900/50 rounded-xl p-5 border border-green-500/40 hover:border-green-400/80 transition-all duration-300 cursor-pointer hover:shadow-lg hover:shadow-green-500/30 relative overflow-hidden"
                   onClick={() => setExpandedGraph('throughput')}>
                <div className="absolute top-0 right-0 w-24 h-24 bg-green-400/5 rounded-full blur-2xl" />
                <div className="text-green-300/80 text-xs font-medium tracking-wider uppercase mb-1">Combined Throughput (UL+DL)</div>
                <div className="text-5xl font-black text-green-400 tracking-tight"><AnimatedNumber value={graphData[graphData.length - 1]?.combined || 0} /> <span className="text-2xl font-semibold text-green-400/70">Gbps</span></div>
              </div>

              {/* Active UE Sessions KPI - HERO SIZE */}
              <div className="mb-4 bg-gradient-to-br from-purple-900/50 to-pink-900/50 rounded-xl p-5 border border-purple-500/40 hover:border-purple-400/80 transition-all duration-300 cursor-pointer hover:shadow-lg hover:shadow-purple-500/30 relative overflow-hidden"
                   onClick={() => setExpandedGraph('sessions')}>
                <div className="absolute top-0 right-0 w-24 h-24 bg-purple-400/5 rounded-full blur-2xl" />
                <div className="text-purple-300/80 text-xs font-medium tracking-wider uppercase mb-1">Active UE Sessions</div>
                <div className="text-5xl font-black text-purple-400 tracking-tight"><AnimatedNumber value={sessionData[sessionData.length - 1]?.sessions || 0} decimals={0} /></div>
              </div>

              {/* Throughput Detail */}
              <div className="mb-4 bg-gradient-to-br from-blue-900/50 to-cyan-900/50 rounded-xl p-4 border border-blue-500/30 hover:border-blue-400/60 transition-all duration-300 cursor-pointer hover:shadow-lg hover:shadow-blue-500/20"
                   onClick={() => setExpandedGraph('throughput-detail')}>
                <div className="text-blue-300/70 text-xs font-medium tracking-wider uppercase mb-2">Throughput</div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-xs text-gray-500 mb-0.5">RX (Uplink)</div>
                    <div className="text-3xl font-bold text-blue-400"><AnimatedNumber value={graphData[graphData.length - 1]?.rxGbps || 0} /> <span className="text-sm text-blue-400/60">Gbps</span></div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-0.5">TX (Downlink)</div>
                    <div className="text-3xl font-bold text-green-400"><AnimatedNumber value={graphData[graphData.length - 1]?.txGbps || 0} /> <span className="text-sm text-green-400/60">Gbps</span></div>
                  </div>
                </div>
              </div>

              {/* CPU Detail */}
              <div className="bg-gradient-to-br from-green-900/50 to-emerald-900/50 rounded-xl p-4 border border-green-500/30 hover:border-green-400/60 transition-all duration-300 cursor-pointer hover:shadow-lg hover:shadow-green-500/20"
                   onClick={() => setExpandedGraph('cpu')}>
                <div className="text-green-300/70 text-xs font-medium tracking-wider uppercase mb-2">CPU Utilization</div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-xs text-gray-500 mb-0.5">Node (192 vCPU)</div>
                    <div className="text-3xl font-bold text-green-400"><AnimatedNumber value={graphData[graphData.length - 1]?.nodeCpu || 0} decimals={0} /><span className="text-sm text-green-400/60">%</span></div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-0.5">DPDK Workers</div>
                    <div className="text-3xl font-bold text-yellow-400"><AnimatedNumber value={graphData[graphData.length - 1]?.avgCpu || 0} decimals={0} /><span className="text-sm text-yellow-400/60">%</span></div>
                    <div className="text-[9px] text-gray-500 mt-0.5">poll-mode · expected</div>
                  </div>
                </div>
              </div>

              {/* App Forwarding Stats */}
              <div className="mt-4 bg-gradient-to-br from-cyan-900/50 to-blue-900/50 rounded-xl p-4 border border-cyan-500/30 hover:border-cyan-400/60 transition-all duration-300 cursor-pointer hover:shadow-lg hover:shadow-cyan-500/20">
                <div className="text-cyan-300/70 text-xs font-medium tracking-wider uppercase mb-2">App Forwarding</div>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <div className="text-xs text-gray-500 mb-0.5">Packets In</div>
                    <div className="text-3xl font-bold text-cyan-400">{upfStats.ipackets >= 1e12 ? (upfStats.ipackets / 1e12).toFixed(1) : (upfStats.ipackets / 1e9).toFixed(1)}<span className="text-sm text-cyan-400/60">{upfStats.ipackets >= 1e12 ? 'T' : 'B'}</span></div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-0.5">Forwarded</div>
                    <div className="text-3xl font-bold text-green-400">{upfStats.opackets >= 1e12 ? (upfStats.opackets / 1e12).toFixed(1) : (upfStats.opackets / 1e9).toFixed(1)}<span className="text-sm text-green-400/60">{upfStats.opackets >= 1e12 ? 'T' : 'B'}</span></div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 mb-0.5">Packet Loss</div>
                    <div className={`text-3xl font-bold ${upfStats.totalLoss < 0.1 ? 'text-green-400' : 'text-red-400'}`}>{upfStats.totalLoss.toFixed(3)}<span className="text-sm opacity-60">%</span></div>
                  </div>
                </div>
              </div>
            </div>

            {/* Alarm Management */}
            <div className="bg-gray-800/80 backdrop-blur-md rounded-2xl shadow-2xl p-6 border border-gray-700/50 hover:border-red-500/50 transition-all duration-300">
              <h2 className="text-xl font-semibold text-white mb-4 flex items-center gap-2">
                <AlertTriangle size={24} className="text-red-400 animate-pulse" />
                Alarms
              </h2>
              
              {/* Alarm Filters */}
              <div className="flex gap-2 mb-4 flex-wrap">
                <button
                  onClick={() => setAlarmFilter('all')}
                  className={`px-3 py-1 rounded text-sm ${
                    alarmFilter === 'all'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  All ({alarms.length})
                </button>
                <button
                  onClick={() => setAlarmFilter('critical')}
                  className={`px-3 py-1 rounded text-sm ${
                    alarmFilter === 'critical'
                      ? 'bg-red-600 text-white'
                      : 'bg-red-900/30 text-red-400 hover:bg-red-900/50'
                  }`}
                >
                  Critical ({alarms.filter(a => a.priority === 'critical').length})
                </button>
                <button
                  onClick={() => setAlarmFilter('warning')}
                  className={`px-3 py-1 rounded text-sm ${
                    alarmFilter === 'warning'
                      ? 'bg-yellow-600 text-white'
                      : 'bg-yellow-900/30 text-yellow-400 hover:bg-yellow-900/50'
                  }`}
                >
                  Warning ({alarms.filter(a => a.priority === 'warning').length})
                </button>
                <button
                  onClick={() => setAlarmFilter('info')}
                  className={`px-3 py-1 rounded text-sm ${
                    alarmFilter === 'info'
                      ? 'bg-blue-600 text-white'
                      : 'bg-blue-900/30 text-blue-400 hover:bg-blue-900/50'
                  }`}
                >
                  Info ({alarms.filter(a => a.priority === 'info').length})
                </button>
              </div>

              {/* Alarm List */}
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {loadingAlarms ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="animate-spin text-red-400" size={24} />
                    <span className="ml-2 text-gray-400">Loading alarms...</span>
                  </div>
                ) : filteredAlarms.length === 0 ? (
                  <div className="text-center py-8 text-gray-400">No alarms</div>
                ) : (
                  filteredAlarms.map(alarm => (
                    <div
                      key={alarm.id}
                      className={`p-3 rounded ${getAlarmColor(alarm.priority)}`}
                    >
                      <div className="flex justify-between items-start mb-1">
                        <span className="font-semibold text-xs uppercase">{alarm.priority}</span>
                        <span className="text-xs opacity-75">{alarm.time}</span>
                      </div>
                      <div className="text-sm">{alarm.message}</div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* GitLab Issues (Day2 Monitor) */}
            <div className="bg-gray-800/80 backdrop-blur-md rounded-2xl shadow-2xl p-5 border border-gray-700/50 hover:border-orange-500/50 transition-all duration-300">
              <h2 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
                <span className="text-xl">🦊</span>
                GitLab Issues
                <a href={`https://gitlab.com/amazon-web-services-group1/nec-mwc-2026/-/issues`} target="_blank" rel="noopener noreferrer" className="ml-auto text-xs text-gray-500 hover:text-orange-400 transition-colors">Open ↗</a>
              </h2>
              <GitLabIssues />
            </div>
          </div>
        </div>

        {/* Graph Expanded Modal */}
        {expandedGraph && (
          <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4 animate-fadeIn"
               onClick={() => setExpandedGraph(null)}>
            <div className="bg-gradient-to-br from-gray-800/95 to-gray-900/95 backdrop-blur-xl rounded-2xl w-full max-w-4xl h-96 flex flex-col border border-purple-500/30 shadow-2xl shadow-purple-500/20"
                 onClick={(e) => e.stopPropagation()}>
              <div className="flex justify-between items-center p-4 border-b border-gray-700/50">
                <div className="w-8"></div>
                <h3 className="text-xl font-bold text-white flex-1 text-center">
                  {expandedGraph === 'throughput' ? 'Combined Throughput (UL+DL)' : 
                   expandedGraph === 'throughput-detail' ? 'RX & TX Throughput' :
                   expandedGraph === 'sessions' ? 'Active UE Sessions' :
                   'CPU Usage (Avg & Max)'}
                </h3>
                <button
                  onClick={() => setExpandedGraph(null)}
                  className="text-gray-400 hover:text-white text-2xl w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-700/50 transition-all duration-300"
                >
                  ×
                </button>
              </div>
              
              <div className="flex-1 p-4">
                {expandedGraph === 'throughput' ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={graphData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis dataKey="time" stroke="#9CA3AF" fontSize={11} />
                      <YAxis stroke="#9CA3AF" label={{ value: 'Gbps', angle: -90, position: 'insideLeft', fill: '#9CA3AF' }} domain={['auto', 'auto']} />
                      <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #10B981' }} />
                      <Legend />
                      <Line type="monotone" dataKey="combined" stroke="#10B981" strokeWidth={3} name="Combined Throughput (Gbps)" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : expandedGraph === 'throughput-detail' ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={graphData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis dataKey="time" stroke="#9CA3AF" fontSize={11} />
                      <YAxis stroke="#9CA3AF" label={{ value: 'Gbps', angle: -90, position: 'insideLeft', fill: '#9CA3AF' }} domain={['auto', 'auto']} />
                      <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #3B82F6' }} />
                      <Legend />
                      <Line type="monotone" dataKey="rxGbps" stroke="#3B82F6" strokeWidth={3} name="RX Gbps" dot={false} />
                      <Line type="monotone" dataKey="txGbps" stroke="#10B981" strokeWidth={3} name="TX Gbps" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : expandedGraph === 'sessions' ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={sessionData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis dataKey="time" stroke="#9CA3AF" fontSize={11} />
                      <YAxis stroke="#9CA3AF" label={{ value: 'Sessions', angle: -90, position: 'insideLeft', fill: '#9CA3AF' }} />
                      <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #A855F7' }} />
                      <Line type="monotone" dataKey="sessions" stroke="#A855F7" strokeWidth={3} name="Active Sessions" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={graphData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                      <XAxis dataKey="time" stroke="#9CA3AF" fontSize={11} />
                      <YAxis stroke="#9CA3AF" label={{ value: '%', angle: -90, position: 'insideLeft', fill: '#9CA3AF' }} domain={['auto', 'auto']} />
                      <Tooltip contentStyle={{ backgroundColor: '#1F2937', border: '1px solid #F59E0B' }} />
                      <Legend />
                      <Line type="monotone" dataKey="avgCpu" stroke="#F59E0B" strokeWidth={3} name="Avg CPU %" dot={false} />
                      <Line type="monotone" dataKey="maxCpu" stroke="#EF4444" strokeWidth={3} name="Max CPU %" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Slides Expanded Modal */}
        {slidesExpanded && (
          <div ref={slidesContainerRef} className="fixed inset-0 bg-black flex items-center justify-center z-50 animate-fadeIn">
            <div className="w-full h-full flex flex-col">
              
              <div className="flex-1 flex items-center justify-center relative bg-black">
                <img
                  src={`/slides/slide-${currentSlide}.jpg`}
                  alt={`Slide ${currentSlide}`}
                  className="w-full h-full object-contain"
                />
                
                {/* Navigation Buttons */}
                <button
                  onClick={() => setCurrentSlide(prev => Math.max(1, prev - 1))}
                  disabled={currentSlide === 1}
                  className="absolute left-4 top-1/2 -translate-y-1/2 bg-gray-800/90 hover:bg-gray-700 text-white p-4 rounded-full shadow-lg disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-300 hover:scale-110"
                >
                  <ChevronLeft size={32} />
                </button>
                
                <button
                  onClick={() => setCurrentSlide(prev => Math.min(totalSlides, prev + 1))}
                  disabled={currentSlide === totalSlides}
                  className="absolute right-4 top-1/2 -translate-y-1/2 bg-gray-800/90 hover:bg-gray-700 text-white p-4 rounded-full shadow-lg disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-300 hover:scale-110"
                >
                  <ChevronRight size={32} />
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Create SOP Modal */}
        {showCreateModal && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-gray-800 rounded-lg p-6 w-96">
              <h3 className="text-xl font-semibold text-white mb-4">Create New SOP</h3>
              <input
                type="text"
                value={newSopName}
                onChange={(e) => setNewSopName(e.target.value)}
                placeholder="e.g., 08-new-deployment.md"
                className="w-full bg-gray-900 text-white p-3 rounded mb-4"
                onKeyPress={(e) => e.key === 'Enter' && createSop()}
                autoFocus
              />
              <div className="flex gap-2">
                <button
                  onClick={createSop}
                  className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded"
                >
                  Create
                </button>
                <button
                  onClick={() => { setShowCreateModal(false); setNewSopName('') }}
                  className="flex-1 px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default App
