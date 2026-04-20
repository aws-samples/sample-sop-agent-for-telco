// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from 'react'
import { Maximize2, X } from 'lucide-react'
import { STRANDS_LOGO } from './AgentStatusIndicator'

const TOOL_GROUPS = {
  kubectl: 'K8s', kubectl_exec: 'K8s', get_pod_name: 'K8s', check_pod_status: 'K8s',
  get_pod_logs: 'K8s', describe_node: 'K8s', argocd_sync: 'GitOps', argocd_status: 'GitOps',
  ssh_command: 'SSH', ssh_expect: 'SSH', run_command: 'Shell', telcocli: 'Telco',
  read_sop: 'SOP', parse_sop: 'SOP', list_sops: 'SOP',
}

// Derive model from node_id pattern — eval/correct nodes don't use a model
function inferModel(nodeId) {
  if (nodeId.startsWith('eval-')) return 'eval'
  if (nodeId.startsWith('correct-')) return 'opus'
  // Complexity heuristic mirrors select_model: higher stage SOPs tend to be more complex
  const m = nodeId.match(/^(\d+)-/)
  if (!m) return 'haiku'
  const stage = parseInt(m[1])
  if (stage >= 7) return 'opus'
  if (stage >= 3) return 'sonnet'
  return 'haiku'
}

const MODEL_COLORS = {
  haiku:  { bg: '#164e63', border: '#22d3ee', text: '#67e8f9', label: 'Haiku' },
  sonnet: { bg: '#4a1d96', border: '#a78bfa', text: '#c4b5fd', label: 'Sonnet' },
  opus:   { bg: '#831843', border: '#f472b6', text: '#f9a8d4', label: 'Opus' },
  eval:   { bg: '#1c1917', border: '#fbbf24', text: '#fde68a', label: 'Eval' },
}

function AgentFlowSVG({ agentStatus, graphNodes }) {
  const [pulse, setPulse] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setPulse(p => (p + 1) % 100), 40)
    return () => clearInterval(t)
  }, [])

  const isRunning = agentStatus?.status === 'running'
  const currentTool = agentStatus?.current_tool || ''
  const activeToolGroup = TOOL_GROUPS[currentTool]
  const nodes = graphNodes || {}
  const nodeIds = Object.keys(nodes)
  const hasNodes = nodeIds.length > 0

  // ── Layout ──
  const W = 540, orchY = 28, agentY = 96
  const maxCols = 4, nodeW = 96, nodeH = 38, gapX = 14, gapY = 16
  const gridW = nodeW + gapX
  const agentStartX = (W - Math.min(nodeIds.length, maxCols) * gridW + gapX) / 2

  const nodePositions = nodeIds.map((id, i) => ({
    id, x: agentStartX + (i % maxCols) * gridW, y: agentY + Math.floor(i / maxCols) * (nodeH + gapY),
  }))
  const totalRows = nodePositions.length > 0 ? Math.floor((nodeIds.length - 1) / maxCols) + 1 : 0

  const toolY = hasNodes ? agentY + totalRows * (nodeH + gapY) + 20 : 160
  const infraY = toolY + 48
  const futureY = infraY + 56
  const svgH = futureY + 34

  const stateColors = {
    pending: { fill: '#0f172a', stroke: '#334155', text: '#475569' },
    running: { fill: '#1e1b4b', stroke: '#a78bfa', text: '#c4b5fd' },
    success: { fill: '#052e16', stroke: '#22c55e', text: '#86efac' },
    failed:  { fill: '#450a0a', stroke: '#ef4444', text: '#fca5a5' },
  }

  const TierLabel = ({ y, label, color }) => (
    <g>
      <rect x="2" y={y - 8} width="44" height="14" rx="7" fill={color} opacity="0.08" stroke={color} strokeWidth="0.3" />
      <text x="24" y={y + 1} textAnchor="middle" fill={color} fontSize="5" fontWeight="800" opacity="0.7">{label}</text>
    </g>
  )
  const TierLine = ({ y }) => <line x1="50" y1={y} x2={W - 6} y2={y} stroke="#334155" strokeWidth="0.3" strokeDasharray="4,3" />

  return (
    <svg viewBox={`0 0 ${W} ${svgH}`} className="w-full h-full" preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id="orchGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#7c3aed" /><stop offset="100%" stopColor="#a78bfa" />
        </linearGradient>
        <filter id="glow"><feGaussianBlur stdDeviation="2" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>

      {/* ═══ TIER 1: ORCHESTRATION ═══ */}
      <TierLabel y={orchY - 2} label="ORCH" color="#a78bfa" />
      <g>
        {isRunning && <rect x={W/2 - 130} y={orchY - 16} width="260" height="40" rx="12" fill="#7c3aed" opacity="0.06" filter="url(#glow)" />}
        <rect x={W/2 - 125} y={orchY - 14} width="250" height="36" rx="10" fill="url(#orchGrad)" opacity={isRunning ? 0.22 : 0.1} stroke="#a78bfa" strokeWidth={isRunning ? 1 : 0.5} />
        <image href={STRANDS_LOGO} x={W/2 - 115} y={orchY - 10} width="30" height="30" />
        <text x={W/2 + 10} y={orchY + 3} textAnchor="middle" fill="white" fontSize="9.5" fontWeight="bold">Agentic Workflow Engine</text>
        <text x={W/2 + 10} y={orchY + 14} textAnchor="middle" fill="#c4b5fd" fontSize="5.5" opacity="0.8">
          {hasNodes ? `${nodeIds.length} nodes • DAG execution • Amazon Bedrock` : 'Strands Agents SDK • Dynamic DAG • Amazon Bedrock'}
        </text>
        {isRunning && (
          <circle cx={W/2 - 100} cy={orchY + 5} r="18" fill="none" stroke="#a78bfa" strokeWidth="0.8" strokeDasharray="8,5" opacity="0.4">
            <animateTransform attributeName="transform" type="rotate" from={`0 ${W/2 - 100} ${orchY + 5}`} to={`360 ${W/2 - 100} ${orchY + 5}`} dur="3s" repeatCount="indefinite" />
          </circle>
        )}
      </g>

      {/* ═══ TIER 2: AGENTS (with model badges) ═══ */}
      <TierLine y={orchY + 26} />
      <TierLabel y={agentY - 12} label="AGENTS" color="#818cf8" />

      {/* Fan-out lines from orchestrator to agents — rendered FIRST so they're behind capsules */}
      {nodePositions.map(np => {
        const state = nodes[np.id]?.status || 'running'
        return (
          <line key={`line-${np.id}`} x1={W/2} y1={orchY + 22} x2={np.x + nodeW/2} y2={np.y}
            stroke={state === 'running' ? '#a78bfa' : state === 'success' ? '#22c55e' : '#334155'}
            strokeWidth={state === 'running' ? 0.8 : 0.3} strokeDasharray={state === 'running' ? 'none' : '3,2'}
            opacity={state === 'running' ? 0.6 : 0.15}>
            {state === 'running' && <animate attributeName="opacity" values="0.3;0.7;0.3" dur="1.5s" repeatCount="indefinite" />}
          </line>
        )
      })}

      {nodePositions.map(np => {
        const state = nodes[np.id]?.status || 'running'
        const c = stateColors[state] || stateColors.running
        const timeSec = nodes[np.id]?.time_ms ? (nodes[np.id].time_ms >= 1000 ? (nodes[np.id].time_ms / 1000).toFixed(0) + 's' : nodes[np.id].time_ms + 'ms') : ''
        const model = inferModel(np.id)
        const mc = MODEL_COLORS[model] || MODEL_COLORS.haiku
        const isEval = np.id.startsWith('eval-')
        const isCorrect = np.id.startsWith('correct-')
        const label = np.id.replace(/^(eval-|correct-)/, '').replace(/^\d+-/, '').replace(/-/g, ' ')
        const shortLabel = label.length > 12 ? label.substring(0, 11) + '…' : label
        const icon = isEval ? '🧪' : isCorrect ? '🔧' : '🤖'

        return (
          <g key={np.id}>
            {state === 'running' && <rect x={np.x - 2} y={np.y - 2} width={nodeW + 4} height={nodeH + 4} rx="8" fill="#a78bfa" opacity="0.06" filter="url(#glow)" />}
            <rect x={np.x} y={np.y} width={nodeW} height={nodeH} rx="7" fill={c.fill} stroke={c.stroke} strokeWidth={state === 'running' ? 1 : 0.5} />

            {/* Icon + name */}
            <text x={np.x + 10} y={np.y + 14} fill={c.text} fontSize="9">{icon}</text>
            <text x={np.x + 22} y={np.y + 13} fill={c.text} fontSize="6.5" fontWeight="600">{shortLabel}</text>

            {/* Model badge */}
            <rect x={np.x + 2} y={np.y + nodeH - 14} width="30" height="11" rx="3" fill={mc.bg} stroke={mc.border} strokeWidth="0.4" />
            <text x={np.x + 17} y={np.y + nodeH - 6} textAnchor="middle" fill={mc.text} fontSize="4.5" fontWeight="700">{mc.label}</text>

            {/* Eval score badge */}
            {isEval && nodes[np.id]?.avgScore != null && (() => {
              const score = nodes[np.id].avgScore
              const sc = score >= 0.8 ? '#22c55e' : score >= 0.5 ? '#fbbf24' : '#ef4444'
              return (
                <g>
                  <rect x={np.x + 34} y={np.y + nodeH - 14} width="28" height="11" rx="3" fill={score >= 0.8 ? '#052e16' : score >= 0.5 ? '#422006' : '#450a0a'} stroke={sc} strokeWidth="0.4" />
                  <text x={np.x + 48} y={np.y + nodeH - 6} textAnchor="middle" fill={sc} fontSize="5" fontWeight="700">{score.toFixed(2)}</text>
                </g>
              )
            })()}

            {/* Time badge */}
            {timeSec && (
              <text x={np.x + nodeW - 6} y={np.y + nodeH - 5} textAnchor="end" fill={c.text} fontSize="5" opacity="0.7">{timeSec}</text>
            )}

            {/* Status indicator */}
            {state === 'running' && (
              <circle cx={np.x + nodeW - 8} cy={np.y + 10} r="3.5" fill="none" stroke="#a78bfa" strokeWidth="0.7" strokeDasharray="4,3">
                <animateTransform attributeName="transform" type="rotate" from={`0 ${np.x + nodeW - 8} ${np.y + 10}`} to={`360 ${np.x + nodeW - 8} ${np.y + 10}`} dur="1s" repeatCount="indefinite" />
              </circle>
            )}
            {state === 'success' && <text x={np.x + nodeW - 8} y={np.y + 13} textAnchor="middle" fill="#22c55e" fontSize="9">✓</text>}
            {state === 'failed' && <text x={np.x + nodeW - 8} y={np.y + 13} textAnchor="middle" fill="#ef4444" fontSize="9">✗</text>}

            {/* Line down to active tool */}
            {!isEval && state === 'running' && activeToolGroup && (() => {
              const tw = 74, tgap = (W - 56 - 5 * tw) / 4
              const toolCx = (i) => 56 + i * (tw + tgap) + tw / 2
              const groupIdx = { K8s: 0, GitOps: 1, SSH: 2, Shell: 2, Telco: 3, SOP: 4 }
              const ti = groupIdx[activeToolGroup]
              return ti != null ? (
                <line x1={np.x + nodeW/2} y1={np.y + nodeH} x2={toolCx(ti)} y2={toolY - 6}
                  stroke="#a78bfa" strokeWidth="0.8" opacity="0.6">
                  <animate attributeName="opacity" values="0.3;0.8;0.3" dur="1.5s" repeatCount="indefinite" />
                </line>
              ) : null
            })()}
            {/* Faint line down to tools when not active */}
            {!isEval && !(state === 'running' && activeToolGroup) && (
              <line x1={np.x + nodeW/2} y1={np.y + nodeH} x2={np.x + nodeW/2} y2={toolY - 6}
                stroke="#33415515" strokeWidth="0.3" strokeDasharray="2,3" />
            )}
          </g>
        )
      })}

      {/* Idle placeholder agents */}
      {!hasNodes && (
        <g>
          {[0, 1, 2].map(i => {
            const x = 90 + i * 120, y = agentY
            const models = ['Haiku', 'Sonnet', 'Opus']
            const mc = [MODEL_COLORS.haiku, MODEL_COLORS.sonnet, MODEL_COLORS.opus]
            return (
              <g key={i}>
                <line x1={W/2} y1={orchY + 22} x2={x + 48} y2={y} stroke="#33415540" strokeWidth="0.3" strokeDasharray="3,2" />
                <rect x={x} y={y} width="96" height="38" rx="7" fill="#1e293b" stroke="#334155" strokeWidth="0.4" strokeDasharray={i === 2 ? '3,2' : 'none'} />
                <text x={x + 11} y={y + 15} fill="#475569" fontSize="9">🤖</text>
                <text x={x + 56} y={y + 15} textAnchor="middle" fill="#475569" fontSize="6.5">SOP Agent</text>
                <rect x={x + 2} y={y + 24} width="32" height="11" rx="3" fill={mc[i].bg} stroke={mc[i].border} strokeWidth="0.3" opacity="0.5" />
                <text x={x + 18} y={y + 32} textAnchor="middle" fill={mc[i].text} fontSize="4.5" opacity="0.5">{models[i]}</text>
              </g>
            )
          })}
          <text x="440" y={agentY + 22} fill="#475569" fontSize="13">⋯</text>
        </g>
      )}

      {/* ═══ TIER 3: TOOLS ═══ */}
      <TierLine y={toolY - 8} />
      <TierLabel y={toolY} label="TOOLS" color="#22d3ee" />
      <g>
        {[
          { label: 'kubectl',   color: '#22d3ee', icon: '☸', group: 'K8s' },
          { label: 'ArgoCD',    color: '#f472b6', icon: '🔄', group: 'GitOps' },
          { label: 'SSH',       color: '#fb923c', icon: '🔗', group: 'SSH' },
          { label: 'TelcoCLI',  color: '#a78bfa', icon: '🗼', group: 'Telco' },
          { label: 'SOP Parse', color: '#94a3b8', icon: '📄', group: 'SOP' },
        ].map((item, i) => {
          const tw = 74, tgap = (W - 56 - 5 * tw) / 4
          const tx = 56 + i * (tw + tgap)
          const active = isRunning && activeToolGroup === item.group
          return (
            <g key={item.label} data-tool-x={tx} data-tool-cx={tx + tw/2}>
              {active && <rect x={tx - 2} y={toolY - 8} width={tw + 4} height="24" rx="6" fill={item.color} opacity="0.08" filter="url(#glow)" />}
              <rect x={tx} y={toolY - 6} width={tw} height="20" rx="5" fill="#0f172a" stroke={item.color} strokeWidth={active ? 0.8 : 0.3} />
              <text x={tx + 12} y={toolY + 7} fill={item.color} fontSize="8">{item.icon}</text>
              <text x={tx + tw/2 + 4} y={toolY + 7} textAnchor="middle" fill={item.color} fontSize="5.5" fontWeight="600">{item.label}</text>
              {active && <text x={tx + tw - 6} y={toolY + 7} fill={item.color} fontSize="6">⚡</text>}
            </g>
          )
        })}
      </g>

      {/* ═══ TIER 4: INFRASTRUCTURE ═══ */}
      <TierLine y={infraY - 8} />
      <TierLabel y={infraY + 10} label="INFRA" color="#38bdf8" />

      {/* Tool → Infra connecting lines */}
      {(() => {
        const tw = 74, tgap = (W - 56 - 5 * tw) / 4
        const toolCx = (i) => 56 + i * (tw + tgap) + tw / 2
        // Target centers: ArgoCD inner=112, EKS center=210, SSH→TestServers=497, TelcoCLI→EKS=210
        const targets = { K8s: 210, GitOps: 112, SSH: 497, Telco: 210 }
        const links = [
          { ti: 0, color: '#22d3ee', group: 'K8s' },
          { ti: 1, color: '#f472b6', group: 'GitOps' },
          { ti: 2, color: '#fb923c', group: 'SSH' },
          { ti: 3, color: '#a78bfa', group: 'Telco' },
        ]
        return links.map(link => {
          const active = isRunning && activeToolGroup === link.group
          return (
            <line key={link.group} x1={toolCx(link.ti)} y1={toolY + 14} x2={targets[link.group]} y2={infraY - 4}
              stroke={link.color} strokeWidth={active ? 0.8 : 0.3} strokeDasharray={active ? 'none' : '3,2'}
              opacity={active ? 0.6 : 0.15}>
              {active && <animate attributeName="opacity" values="0.3;0.7;0.3" dur="1.5s" repeatCount="indefinite" />}
            </line>
          )
        })
      })()}

      {/* Big EKS on Outposts container */}
      <rect x="60" y={infraY - 6} width="300" height="44" rx="8" fill="#0c4a6e" opacity="0.08" stroke="#38bdf8" strokeWidth="0.5" />
      <text x="70" y={infraY + 4} fill="#38bdf8" fontSize="5.5" fontWeight="700" opacity="0.8">☸ Target Infrastructure (EKS)</text>

      {/* Inner: ArgoCD */}
      <rect x="72" y={infraY + 10} width="80" height="20" rx="5" fill="#0f172a" stroke="#f472b6" strokeWidth="0.3" />
      <text x="82" y={infraY + 23} fill="#f472b6" fontSize="7" opacity="0.8">🔄</text>
      <text x="118" y={infraY + 23} textAnchor="middle" fill="#f472b6" fontSize="5.5" fontWeight="600" opacity="0.7">ArgoCD</text>

      {/* Inner: Vendor App */}
      <rect x="162" y={infraY + 10} width="80" height="20" rx="5" fill="#0f172a" stroke="#22c55e" strokeWidth="0.3" />
      <text x="172" y={infraY + 23} fill="#22c55e" fontSize="7" opacity="0.8">📡</text>
      <text x="208" y={infraY + 23} textAnchor="middle" fill="#22c55e" fontSize="5.5" fontWeight="600" opacity="0.7">Vendor App</text>

      {/* Inner: Prometheus */}
      <rect x="252" y={infraY + 10} width="96" height="20" rx="5" fill="#0f172a" stroke="#fbbf24" strokeWidth="0.3" />
      <text x="262" y={infraY + 23} fill="#fbbf24" fontSize="7" opacity="0.8">📊</text>
      <text x="306" y={infraY + 23} textAnchor="middle" fill="#fbbf24" fontSize="5.5" fontWeight="600" opacity="0.7">Prometheus</text>

      {/* External: GitLab */}
      <rect x="380" y={infraY - 2} width="70" height="20" rx="5" fill="none" stroke="#fb923c" strokeWidth="0.4" strokeDasharray="3,2" opacity="0.5" />
      <text x="389" y={infraY + 11} fill="#fb923c" fontSize="6" opacity="0.6">🔀</text>
      <text x="421" y={infraY + 11} textAnchor="middle" fill="#fb923c" fontSize="5" fontWeight="600" opacity="0.7">GitLab</text>

      {/* External: Test Servers */}
      <rect x="460" y={infraY - 2} width="74" height="20" rx="5" fill="none" stroke="#fbbf24" strokeWidth="0.4" strokeDasharray="3,2" opacity="0.5" />
      <text x="469" y={infraY + 11} fill="#fbbf24" fontSize="6" opacity="0.6">🖥</text>
      <text x="503" y={infraY + 11} textAnchor="middle" fill="#fbbf24" fontSize="5" fontWeight="600" opacity="0.7">Test Servers</text>

      {/* Sync arrow: GitLab → ArgoCD */}
      <line x1="380" y1={infraY + 8} x2="360" y2={infraY + 20} stroke="#fb923c" strokeWidth="0.4" strokeDasharray="2,2" opacity="0.4" />
      <text x="366" y={infraY + 16} fill="#fb923c" fontSize="3.5" opacity="0.4">sync</text>

      {/* ═══ CONTROL PLANE (Region) ═══ */}
      <TierLine y={futureY - 8} />
      <g opacity="0.45">
        <rect x="60" y={futureY - 4} width="300" height="28" rx="8" fill="#1e1b4b" opacity="0.08" stroke="#a78bfa" strokeWidth="0.4" strokeDasharray="4,3" />
        <text x="70" y={futureY + 7} fill="#a78bfa" fontSize="5.5" fontWeight="700">☸ EKS in Region (us-east-1) — Control Plane</text>

        <rect x="72" y={futureY + 12} width="68" height="12" rx="3" fill="none" stroke="#f472b6" strokeWidth="0.3" strokeDasharray="2,2" />
        <text x="80" y={futureY + 21} fill="#f472b6" fontSize="4.5">🔄</text>
        <text x="112" y={futureY + 21} textAnchor="middle" fill="#f472b6" fontSize="4.5" fontWeight="600">ArgoCD</text>

        <rect x="150" y={futureY + 12} width="110" height="12" rx="3" fill="none" stroke="#22c55e" strokeWidth="0.3" strokeDasharray="2,2" />
        <text x="158" y={futureY + 21} fill="#22c55e" fontSize="4.5">📡</text>
        <text x="210" y={futureY + 21} textAnchor="middle" fill="#22c55e" fontSize="4.5" fontWeight="600">5G CP (AMF / SMF)</text>

        <rect x="270" y={futureY + 12} width="78" height="12" rx="3" fill="none" stroke="#fbbf24" strokeWidth="0.3" strokeDasharray="2,2" />
        <text x="278" y={futureY + 21} fill="#fbbf24" fontSize="4.5">📊</text>
        <text x="314" y={futureY + 21} textAnchor="middle" fill="#fbbf24" fontSize="4.5" fontWeight="600">Prometheus</text>
      </g>

      {/* ── Active tool callout ── */}
      {isRunning && currentTool && (
        <g>
          <rect x={W/2 - 80} y={toolY + 16} width="160" height="12" rx="4" fill="#1e1b4b" opacity="0.85" stroke="#a78bfa" strokeWidth="0.3" />
          <text x={W/2} y={toolY + 24} textAnchor="middle" fill="#c4b5fd" fontSize="5.5" fontWeight="bold">⚡ {currentTool}</text>
        </g>
      )}

      {/* ── Idle state ── */}
      {!hasNodes && !isRunning && (
        <g>
          <text x={W/2} y={agentY + 48} textAnchor="middle" fill="#64748b" fontSize="5" opacity="0.6">
            Sub-agents created per SOP — model, tools, and dependencies derived from content
          </text>
          <g transform={`translate(90, ${futureY + 26})`}>
            {[
              { l: 'Running', c: '#a78bfa' }, { l: 'Completed', c: '#22c55e' }, { l: 'Failed', c: '#ef4444' },
              { l: 'Haiku', c: '#22d3ee' }, { l: 'Sonnet', c: '#a78bfa' }, { l: 'Opus', c: '#f472b6' },
            ].map((item, i) => (
              <g key={item.l} transform={`translate(${i * 52}, 0)`}>
                <rect x="0" y="0" width="8" height="8" rx="2" fill="none" stroke={item.c} strokeWidth="0.6" />
                <text x="11" y="7" fill={item.c} fontSize="4.5">{item.l}</text>
              </g>
            ))}
          </g>
        </g>
      )}
    </svg>
  )
}

export default function AgentFlowDiagram({ agentStatus, graphNodes }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <div className="bg-gray-800/60 backdrop-blur-md rounded-2xl p-5 border border-purple-500/30 shadow-xl cursor-pointer" onClick={() => setExpanded(true)}>
        <div className="text-lg font-bold text-white mb-2 flex items-center justify-between tracking-wide">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-purple-400 animate-pulse" />
            Agent Execution Flow
          </div>
          <Maximize2 size={16} className="text-purple-400/60" />
        </div>
        <div style={{ height: Math.max(220, Math.min(600, 160 + Math.ceil(Object.keys(graphNodes || {}).length / 4) * 60)) }}><AgentFlowSVG agentStatus={agentStatus} graphNodes={graphNodes} /></div>
      </div>

      {expanded && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-50 p-6" onClick={() => setExpanded(false)}>
          <div className="bg-gradient-to-br from-gray-800/95 to-gray-900/95 rounded-2xl w-full max-w-7xl max-h-[95vh] border border-purple-500/30 shadow-2xl p-8" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div className="text-xl font-semibold text-purple-300 flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-purple-400 animate-pulse" />
                Agentic Workflow Engine
              </div>
              <button onClick={() => setExpanded(false)} className="text-gray-400 hover:text-white w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-700/50">
                <X size={20} />
              </button>
            </div>
            <div style={{ height: 700 }}><AgentFlowSVG agentStatus={agentStatus} graphNodes={graphNodes} /></div>
          </div>
        </div>
      )}
    </>
  )
}
