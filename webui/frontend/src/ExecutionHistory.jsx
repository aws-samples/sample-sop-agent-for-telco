// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useState, useEffect } from 'react'
import { Clock, CheckCircle, XCircle, ChevronDown, ChevronUp } from 'lucide-react'

const ExecutionHistory = () => {
  const [runs, setRuns] = useState([])
  const [expanded, setExpanded] = useState(null)
  const [detail, setDetail] = useState(null)

  useEffect(() => {
    fetch('/api/executions').then(r => r.json()).then(setRuns).catch(() => {})
  }, [])

  const loadDetail = async (runId) => {
    if (expanded === runId) { setExpanded(null); return }
    setExpanded(runId)
    try {
      const data = await fetch(`/api/executions/${runId}`).then(r => r.json())
      setDetail(data)
    } catch { setDetail(null) }
  }

  const fmtDuration = (s) => {
    if (!s) return '—'
    const m = Math.floor(s / 60), sec = Math.round(s % 60)
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`
  }

  const fmtTokens = (n) => {
    if (!n) return '—'
    return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${(n / 1000).toFixed(0)}K` : n
  }

  if (!runs.length) return <div className="text-gray-500 text-sm p-4">No execution history yet.</div>

  return (
    <div className="space-y-2 max-h-[500px] overflow-y-auto p-2">
      {runs.map(run => {
        const s = run.summary || {}
        const isOpen = expanded === run.run_id
        return (
          <div key={run.run_id} className="bg-gray-900/60 rounded-lg border border-gray-700/50">
            <button onClick={() => loadDetail(run.run_id)}
              className="w-full flex items-center justify-between p-3 text-left hover:bg-gray-800/50 rounded-lg transition-all">
              <div className="flex items-center gap-2">
                {run.status === 'completed' ? <CheckCircle size={14} className="text-green-400" /> :
                 run.status === 'interrupted' ? <Clock size={14} className="text-yellow-400" /> :
                 <XCircle size={14} className="text-red-400" />}
                <span className="text-white text-xs font-mono">{run.run_id}</span>
                <span className="text-gray-500 text-xs">{run.sop_paths?.length} SOP{run.sop_paths?.length !== 1 ? 's' : ''}</span>
              </div>
              <div className="flex items-center gap-3 text-xs text-gray-400">
                <span>{fmtDuration(run.duration_s)}</span>
                <span>{s.total_tool_calls || 0} tools</span>
                <span>{fmtTokens(s.total_tokens)}</span>
                {isOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </div>
            </button>

            {isOpen && detail && (
              <div className="px-3 pb-3 space-y-1">
                {Object.entries(detail.nodes || {}).map(([nid, node]) => (
                  <div key={nid} className={`flex items-center justify-between px-2 py-1.5 rounded text-xs ${
                    node.status === 'success' ? 'bg-green-900/20 text-green-300' :
                    node.status === 'failed' ? 'bg-red-900/20 text-red-300' : 'bg-gray-800/50 text-gray-400'
                  }`}>
                    <span className="font-medium">{nid}</span>
                    <div className="flex items-center gap-3">
                      <span>{node.tool_calls?.length || 0} tools</span>
                      <span>{fmtDuration((node.execution_time_ms || 0) / 1000)}</span>
                      {node.eval_scores?.length > 0 && (
                        <span className="text-purple-300">
                          avg {(node.eval_scores.reduce((a, s) => a + s.score, 0) / node.eval_scores.length).toFixed(2)}
                        </span>
                      )}
                      <span className={node.status === 'success' ? 'text-green-400' : 'text-red-400'}>
                        {node.status === 'success' ? '✓' : '✗'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default ExecutionHistory
