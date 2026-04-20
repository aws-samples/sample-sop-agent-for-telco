// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useState, useEffect } from 'react'
import { Clock, CheckCircle, XCircle, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'

const SOPExecutionHistory = ({ sopName, isVisible }) => {
  const [history, setHistory] = useState(null)
  const [loading, setLoading] = useState(false)
  const [showFullLogs, setShowFullLogs] = useState(false)

  useEffect(() => {
    if (isVisible && sopName) {
      fetchHistory()
    }
  }, [sopName, isVisible])

  const fetchHistory = async () => {
    setLoading(true)
    try {
      const response = await fetch(`/api/sop/${sopName}/history`)
      const data = await response.json()
      setHistory(data)
    } catch (error) {
      console.error('Error fetching SOP history:', error)
      setHistory(null)
    } finally {
      setLoading(false)
    }
  }

  const getStepIcon = (status) => {
    switch (status) {
      case 'success':
        return <CheckCircle className="w-4 h-4 text-green-400" />
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-400" />
      default:
        return <Clock className="w-4 h-4 text-blue-400" />
    }
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-400" />
      case 'failed':
        return <XCircle className="w-4 h-4 text-red-400" />
      case 'never_run':
        return <AlertTriangle className="w-4 h-4 text-yellow-400" />
      default:
        return <Clock className="w-4 h-4 text-gray-400" />
    }
  }

  const formatDuration = (start, end) => {
    if (!start || !end) return null
    const duration = new Date(end) - new Date(start)
    return `${Math.round(duration / 1000)}s`
  }

  if (!isVisible) return null

  return (
    <div className="mt-4 backdrop-blur-sm bg-white/5 rounded-lg p-4 border border-white/10">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
          <Clock className="w-5 h-5" />
          Last Execution
        </h3>
        {history && history.logs && history.logs.length > 0 && (
          <button
            onClick={() => setShowFullLogs(true)}
            className="flex items-center gap-1 text-blue-300 hover:text-blue-200 text-sm"
          >
            <ChevronDown className="w-4 h-4" />
            Show Logs
          </button>
        )}
      </div>

      {loading ? (
        <div className="text-gray-400 text-sm">Loading execution history...</div>
      ) : history ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {getStatusIcon(history.status)}
              <span className="text-white capitalize">{history.status}</span>
              {history.exit_code !== null && (
                <span className="text-xs text-gray-400">
                  (exit code: {history.exit_code})
                </span>
              )}
            </div>
            <div className="text-sm text-gray-400">
              {history.start_time && new Date(history.start_time).toLocaleString()}
              {formatDuration(history.start_time, history.end_time) && (
                <span className="ml-2">• {formatDuration(history.start_time, history.end_time)}</span>
              )}
            </div>
          </div>

          {history.last_output && (
            <div className="text-sm text-gray-300 bg-black/20 rounded p-2 font-mono">
              {history.last_output}
            </div>
          )}

          {/* Execution Steps */}
          {history.steps && history.steps.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-sm font-semibold text-white">Execution Steps</h4>
              <div className="space-y-1 max-h-60 overflow-y-auto">
                {history.steps.map((step, index) => (
                  <div key={index} className={`flex items-start gap-3 p-3 rounded-lg transition-all duration-300 ${
                    step.status === 'success' ? 'bg-green-900/20 border border-green-500/40' :
                    step.status === 'failed' ? 'bg-red-900/20 border border-red-500/40' :
                    'bg-blue-900/20 border border-blue-500/40'
                  }`}>
                    <div className="mt-0.5">
                      {getStepIcon(step.status)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className={`text-sm font-medium whitespace-pre-wrap ${
                        step.status === 'success' ? 'text-green-300' :
                        step.status === 'failed' ? 'text-red-300' : 
                        'text-blue-300'
                      }`}>
                        {step.name}
                      </div>
                    </div>
                    <span className={`text-xs px-2.5 py-1 rounded-full font-semibold whitespace-nowrap ${
                      step.status === 'success' ? 'bg-green-500/30 text-green-300 border border-green-500/50' :
                      step.status === 'failed' ? 'bg-red-500/30 text-red-300 border border-red-500/50' : 
                      'bg-blue-500/30 text-blue-300 border border-blue-500/50'
                    }`}>
                      {step.status === 'success' ? '✓ Pass' : step.status === 'failed' ? '✗ Fail' : '⟳ Running'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {showFullLogs && history.logs && history.logs.length > 0 && (
            <div className="fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-50 p-6" onClick={() => setShowFullLogs(false)}>
              <div className="bg-gradient-to-br from-gray-800/95 to-gray-900/95 rounded-2xl w-full max-w-5xl max-h-[85vh] flex flex-col border border-blue-500/30 shadow-2xl" onClick={e => e.stopPropagation()}>
                <div className="flex items-center justify-between p-4 border-b border-gray-700/50">
                  <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                    <Clock className="w-5 h-5 text-blue-400" />
                    Execution Logs — {sopName}
                  </h3>
                  <button onClick={() => setShowFullLogs(false)} className="text-gray-400 hover:text-white text-2xl w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-700/50">×</button>
                </div>
                <div className="flex-1 overflow-y-auto p-4 bg-black/30">
                  <div className="space-y-0.5">
                    {history.logs.map((log, index) => (
                      <div key={index} className="text-xs font-mono">
                        <span className="text-gray-500">{new Date(log.timestamp).toLocaleTimeString()}</span>
                        <span className={`ml-2 ${
                          log.message?.includes('✅') || log.message?.includes('PASS') ? 'text-green-400' :
                          log.message?.includes('❌') || log.message?.includes('FAIL') ? 'text-red-400' :
                          log.message?.includes('🔧') || log.message?.includes('TOOL') ? 'text-cyan-400' :
                          'text-gray-300'
                        }`}>{log.message}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2 text-gray-400">
          <AlertTriangle className="w-4 h-4" />
          <span>This SOP has not been executed yet</span>
        </div>
      )}
    </div>
  )
}

export default SOPExecutionHistory
