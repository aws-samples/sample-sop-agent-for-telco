// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { Clock, CheckCircle, XCircle, Loader2, Radio, Server, Terminal, Search, FileText, RefreshCw, Cpu, Network, Brain, ArrowRight } from 'lucide-react'

export const STRANDS_LOGO = 'data:image/png;base64,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'

const stripAnsi = (text) => text?.replace(/\[[0-9;]*m/g, '') || ''

const TOOLS = {
  'kubectl':          { icon: Server,    label: 'kubectl' },
  'kubectl_exec':     { icon: Terminal,  label: 'kubectl exec' },
  'check_pod_status': { icon: Search,    label: 'pod status' },
  'get_pod_name':     { icon: Search,    label: 'pod lookup' },
  'get_pod_logs':     { icon: FileText,  label: 'pod logs' },
  'describe_node':    { icon: Cpu,       label: 'node info' },
  'read_sop':         { icon: FileText,  label: 'read SOP' },
  'parse_sop':        { icon: FileText,  label: 'parse SOP' },
  'argocd_status':    { icon: RefreshCw, label: 'ArgoCD' },
  'argocd_sync':      { icon: RefreshCw, label: 'ArgoCD sync' },
  'run_command':      { icon: Terminal,  label: 'command' },
  'telcocli':         { icon: Server,    label: 'telcocli' },
}

const parseActivity = (text) => {
  if (!text) return null
  const clean = stripAnsi(text)
  
  const toolMatch = clean.match(/🔧 TOOL: (.*?)\((.*?)\)/)
  if (toolMatch) {
    const name = toolMatch[1].trim()
    const args = toolMatch[2].trim().substring(0, 50)
    const t = TOOLS[name] || { icon: Terminal, label: name }
    return { Icon: t.icon, label: t.label, detail: args, type: 'tool' }
  }
  
  if (clean.includes('✅') && clean.includes('PASS')) return { Icon: CheckCircle, label: 'PASS', detail: clean.replace(/[*✅]/g, '').replace('PASS:', '').trim().substring(0, 60), type: 'pass' }
  if (clean.includes('❌') && clean.includes('FAIL')) return { Icon: XCircle, label: 'FAIL', detail: clean.replace(/[*❌]/g, '').replace('FAIL:', '').trim().substring(0, 60), type: 'fail' }
  if (clean.startsWith('Tool #')) return { Icon: Terminal, label: clean.split(':')[0], detail: clean.split(':').slice(1).join(':').trim(), type: 'tool' }
  if (clean.includes('════') || clean.includes('────') || !clean.trim()) return null
  
  return { Icon: Network, label: 'thinking', detail: clean.substring(0, 60), type: 'think' }
}

const MODEL_LABELS = {
  'sonnet4.5': 'Sonnet 4.5',
  'sonnet': 'Sonnet',
  'haiku': 'Haiku',
  'opus': 'Opus',
}

const AgentStatusIndicator = ({ agentStatus, model }) => {
  const activity = parseActivity(agentStatus.last_output)
  const sopName = agentStatus.current_sop?.split('/').pop()
  const modelLabel = MODEL_LABELS[model] || model || 'LLM'
  const isRunning = agentStatus.status === 'running'

  const statusColors = {
    running:   { dot: 'bg-cyan-400 animate-pulse', text: 'text-cyan-300', glow: 'shadow-cyan-500/20' },
    completed: { dot: 'bg-green-400', text: 'text-green-300', glow: 'shadow-green-500/20' },
    failed:    { dot: 'bg-red-400', text: 'text-red-300', glow: 'shadow-red-500/20' },
    idle:      { dot: 'bg-gray-500', text: 'text-gray-400', glow: '' },
  }
  const c = statusColors[agentStatus.status] || statusColors.idle

  return (
    <div className={`mb-6 backdrop-blur-sm bg-white/5 rounded-xl p-4 border border-white/10 shadow-xl ${c.glow}`}>
      {/* Top row: agent icon + status + SOP name */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          {/* Animated Agent Icon */}
          <div className="relative w-14 h-14 flex-shrink-0">
            {isRunning && (
              <>
                <div className="absolute inset-0 rounded-full border-2 border-cyan-400/60 animate-spin" style={{ animationDuration: '3s', borderTopColor: 'transparent', borderBottomColor: 'transparent' }} />
                <div className="absolute -inset-1 rounded-full border border-purple-400/30 animate-spin" style={{ animationDuration: '5s', animationDirection: 'reverse', borderRightColor: 'transparent', borderLeftColor: 'transparent' }} />
                <div className="absolute inset-0 rounded-full bg-cyan-400/10 animate-pulse" />
              </>
            )}
            <div className={`absolute inset-0.5 rounded-full flex items-center justify-center overflow-hidden ${
              isRunning ? 'bg-gradient-to-br from-gray-900 via-purple-950 to-gray-900' :
              agentStatus.status === 'completed' ? 'bg-gradient-to-br from-gray-900 to-green-950' :
              agentStatus.status === 'failed' ? 'bg-gradient-to-br from-gray-900 to-red-950' :
              'bg-gradient-to-br from-gray-900 to-gray-800'
            }`}>
              {isRunning ? (
                <img src={STRANDS_LOGO} alt="Strands" className="w-12 h-12 object-contain" style={{ imageRendering: 'auto' }} />
              ) : agentStatus.status === 'completed' ? (
                <CheckCircle className="w-6 h-6 text-green-400" />
              ) : agentStatus.status === 'failed' ? (
                <XCircle className="w-6 h-6 text-red-400" />
              ) : (
                <Radio className="w-6 h-6 text-gray-500" />
              )}
            </div>
          </div>

          <div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${c.dot}`} />
              <span className="text-white font-medium text-sm">
                Agent <span className={`capitalize ${c.text}`}>{agentStatus.status}</span>
              </span>
              {sopName && <span className="text-gray-500 text-xs">• {sopName}</span>}
            </div>
            {agentStatus.start_time && (
              <div className="flex items-center gap-1 text-xs text-gray-500 mt-0.5">
                <Clock className="w-3 h-3" />
                {new Date(agentStatus.start_time).toLocaleTimeString()}
                {agentStatus.end_time && <span> → {new Date(agentStatus.end_time).toLocaleTimeString()}</span>}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Brain → Tool pipeline */}
      {isRunning && activity && (
        <div className="flex items-center gap-2 bg-black/20 rounded-lg px-3 py-2">
          {/* LLM Brain */}
          <div className="flex items-center gap-1.5 bg-purple-900/40 rounded-md px-2 py-1 border border-purple-500/30">
            <Brain className="w-4 h-4 text-purple-400" />
            <span className="text-purple-300 text-xs font-semibold">{modelLabel}</span>
          </div>

          <ArrowRight className="w-3 h-3 text-gray-600 animate-pulse" />

          {/* Current Tool */}
          <div className={`flex items-center gap-1.5 rounded-md px-2 py-1 border ${
            activity.type === 'pass' ? 'bg-green-900/40 border-green-500/30' :
            activity.type === 'fail' ? 'bg-red-900/40 border-red-500/30' :
            'bg-cyan-900/40 border-cyan-500/30'
          }`}>
            <activity.Icon className={`w-4 h-4 ${
              activity.type === 'pass' ? 'text-green-400' :
              activity.type === 'fail' ? 'text-red-400' :
              'text-cyan-400'
            } ${activity.type === 'tool' ? 'animate-pulse' : ''}`} />
            <span className={`text-xs font-semibold ${
              activity.type === 'pass' ? 'text-green-300' :
              activity.type === 'fail' ? 'text-red-300' :
              'text-cyan-300'
            }`}>{activity.label}</span>
          </div>

          {/* Detail */}
          <span className="text-xs text-gray-400 truncate flex-1">{activity.detail}</span>
        </div>
      )}

      {/* Completed/Failed last output */}
      {!isRunning && agentStatus.status !== 'idle' && activity && (
        <div className="text-xs text-gray-400 truncate">{activity.detail}</div>
      )}
    </div>
  )
}

export default AgentStatusIndicator
