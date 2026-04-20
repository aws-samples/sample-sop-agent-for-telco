// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useState } from 'react'
import { Maximize2, X } from 'lucide-react'

const nodes = [
  { id: 'sim_ul', label: 'UL Server', x: 29, y: 50, color: '#60a5fa', sub: 'gNB + SMF Sim' },
  { id: 'n3', label: 'N3', x: 120, y: 75, color: '#22d3ee', sub: '100.65.1.0/24 (vrfl1)' },
  { id: 'n4', label: 'N4', x: 120, y: 25, color: '#f472b6', sub: '100.65.0.0/24 (vrfl2)' },
  { id: 'app', label: 'Vendor App', x: 210, y: 50, color: '#a78bfa' },
  { id: 'n6', label: 'N6', x: 275, y: 50, color: '#34d399', sub: '100.65.2.0/24 (vrfl3)' },
  { id: 'sim_dl', label: 'DL Server', x: 351, y: 50, color: '#fbbf24', sub: 'DN Sim (Pktgen)' },
]

const links = [
  { from: 'sim_ul', to: 'n3', bidir: true },
  { from: 'sim_ul', to: 'n4', bidir: true },
  { from: 'n3', to: 'app', bidir: true },
  { from: 'n4', to: 'app', bidir: true },
  { from: 'app', to: 'n6', bidir: true },
  { from: 'n6', to: 'sim_dl', bidir: true },
]

const getNode = (id) => nodes.find(n => n.id === id)

function TopoSVG({ full }) {
  const [pulse, setPulse] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setPulse(p => (p + 1) % 100), 50)
    return () => clearInterval(t)
  }, [])

  const app = getNode('app')

  return (
    <svg viewBox="0 0 380 130" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
      {/* Outpost boundary */}
      <rect x="85" y="3" width="220" height="105" rx="8" fill="none" stroke="#f97316" strokeWidth="1.5" strokeDasharray="6,3" opacity="0.6" />
      <text x="195" y="105" textAnchor="middle" fill="#f97316" fontSize="6.5" fontWeight="600" opacity="0.8">AWS Outpost · bmn-cx2.metal-48xl · 2x ConnectX-7 · 4+4 VFs SR-IOV</text>

      {/* EKS boundary */}
      <rect x="92" y="14" width="200" height="75" rx="5" fill="none" stroke="#38bdf8" strokeWidth="1" strokeDasharray="4,2" opacity="0.5" />
      <text x="192" y="10" textAnchor="middle" fill="#38bdf8" fontSize="6" fontWeight="600" opacity="0.7">Amazon EKS v1.32</text>

      {/* Simulator boxes */}
      <rect x="5" y="20" width="48" height="60" rx="5" fill="none" stroke="#60a5fa" strokeWidth="0.8" strokeDasharray="3,2" opacity="0.4" />
      <text x="29" y="17" textAnchor="middle" fill="#60a5fa" fontSize="5" opacity="0.6">10.10.4.238</text>

      <rect x="327" y="20" width="48" height="60" rx="5" fill="none" stroke="#fbbf24" strokeWidth="0.8" strokeDasharray="3,2" opacity="0.4" />
      <text x="351" y="17" textAnchor="middle" fill="#fbbf24" fontSize="5" opacity="0.6">10.10.2.196</text>

      {/* Bottom label */}
      <text x="190" y="122" textAnchor="middle" fill="#34d399" fontSize="5.5" opacity="0.5">eBGP · Local AS 65100 ↔ Remote AS 64764 · 3 Neighbors</text>

      {/* Links */}
      {links.map((link, i) => {
        const na = getNode(link.from), nb = getNode(link.to)
        const fwd = ((pulse + i * 15) % 100) / 100
        const rev = ((pulse + i * 15 + 50) % 100) / 100
        return (
          <g key={`${link.from}-${link.to}`}>
            <line x1={na.x} y1={na.y} x2={nb.x} y2={nb.y} stroke="rgba(100,200,255,0.3)" strokeWidth="1.5" />
            <circle cx={na.x + (nb.x - na.x) * fwd} cy={na.y + (nb.y - na.y) * fwd} r="3" fill="#22d3ee" opacity="0.9" />
            <circle cx={nb.x + (na.x - nb.x) * rev} cy={nb.y + (na.y - nb.y) * rev} r="2" fill="#a78bfa" opacity="0.7" />
          </g>
        )
      })}

      {/* Nodes */}
      {nodes.map(n => (
        <g key={n.id}>
          {n.id === 'app' && full ? (
            /* Expanded App box in fullscreen */
            <>
              <rect x={n.x - 38} y={n.y - 38} width="76" height="80" rx="6" fill="#a78bfa" opacity="0.1" />
              <rect x={n.x - 35} y={n.y - 35} width="70" height="74" rx="4" fill="#1e1b4b" opacity="0.9" stroke="#a78bfa" strokeWidth="0.8" />
              <text x={n.x} y={n.y - 26} textAnchor="middle" fill="white" fontSize="7" fontWeight="bold">Vendor App</text>
              {/* Interface rows */}
              <text x={n.x - 30} y={n.y - 14} fill="#22d3ee" fontSize="4.5" fontWeight="bold">N3</text>
              <text x={n.x - 10} y={n.y - 14} fill="#94a3b8" fontSize="3.8">ethgrp3505</text>
              <rect x={n.x - 30} y={n.y - 10} width="27" height="5" rx="2" fill="#22d3ee" opacity="0.12" />
              <rect x={n.x + 1} y={n.y - 10} width="27" height="5" rx="2" fill="#a78bfa" opacity="0.12" />
              <text x={n.x - 16} y={n.y - 6.2} textAnchor="middle" fill="#22d3ee" fontSize="3" fontWeight="600">VF · NIC-A</text>
              <text x={n.x + 14.5} y={n.y - 6.2} textAnchor="middle" fill="#a78bfa" fontSize="3" fontWeight="600">VF · NIC-B</text>

              <text x={n.x - 30} y={n.y + 4} fill="#f472b6" fontSize="4.5" fontWeight="bold">N4</text>
              <text x={n.x - 10} y={n.y + 4} fill="#94a3b8" fontSize="3.8">ethgrp3501</text>
              <rect x={n.x - 30} y={n.y + 8} width="27" height="5" rx="2" fill="#f472b6" opacity="0.12" />
              <rect x={n.x + 1} y={n.y + 8} width="27" height="5" rx="2" fill="#a78bfa" opacity="0.12" />
              <text x={n.x - 16} y={n.y + 11.8} textAnchor="middle" fill="#f472b6" fontSize="3" fontWeight="600">VF · NIC-A</text>
              <text x={n.x + 14.5} y={n.y + 11.8} textAnchor="middle" fill="#a78bfa" fontSize="3" fontWeight="600">VF · NIC-B</text>

              <text x={n.x - 30} y={n.y + 22} fill="#34d399" fontSize="4.5" fontWeight="bold">N6</text>
              <text x={n.x - 10} y={n.y + 22} fill="#94a3b8" fontSize="3.8">ethgrp3509</text>
              <rect x={n.x - 30} y={n.y + 26} width="27" height="5" rx="2" fill="#34d399" opacity="0.12" />
              <rect x={n.x + 1} y={n.y + 26} width="27" height="5" rx="2" fill="#a78bfa" opacity="0.12" />
              <text x={n.x - 16} y={n.y + 29.8} textAnchor="middle" fill="#34d399" fontSize="3" fontWeight="600">VF · NIC-A</text>
              <text x={n.x + 14.5} y={n.y + 29.8} textAnchor="middle" fill="#a78bfa" fontSize="3" fontWeight="600">VF · NIC-B</text>
            </>
          ) : (
            /* Normal circle node */
            <>
              <circle cx={n.x} cy={n.y} r={n.id === 'app' ? 20 : 14} fill={n.color} opacity="0.12" />
              <circle cx={n.x} cy={n.y} r={n.id === 'app' ? 15 : 10} fill={n.color} opacity="0.85" />
              <text x={n.x} y={n.y + 2.5} textAnchor="middle" fill="white" fontSize={n.id === 'app' ? '9' : '8'} fontWeight="bold" dominantBaseline="middle">{n.label}</text>
            </>
          )}
          {!(n.id === 'app' && full) && (
            <text x={n.x} y={n.y + (n.id === 'app' ? 22 : 18)} textAnchor="middle" fill={n.color} fontSize="6" opacity="0.85">{n.sub}</text>
          )}
          {n.id === 'app' && full && (
            <text x={n.x} y={n.y + 34} textAnchor="middle" fill={n.color} fontSize="5" opacity="0.85">{n.sub}</text>
          )}
        </g>
      ))}
    </svg>
  )
}

export default function NetworkTopology() {
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <div className="bg-gray-800/60 backdrop-blur-md rounded-2xl p-5 border border-cyan-500/30 shadow-xl cursor-pointer" onClick={() => setExpanded(true)}>
        <div className="text-base font-semibold text-cyan-300 mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-full bg-cyan-400 animate-pulse" />
            Network Topology
          </div>
          <Maximize2 size={16} className="text-cyan-400/60" />
        </div>
        <div style={{ height: 200 }}><TopoSVG full={false} /></div>
      </div>

      {expanded && (
        <div className="fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-50 p-6" onClick={() => setExpanded(false)}>
          <div className="bg-gradient-to-br from-gray-800/95 to-gray-900/95 rounded-2xl w-full max-w-7xl max-h-[95vh] border border-cyan-500/30 shadow-2xl p-8 overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div className="text-xl font-semibold text-cyan-300 flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-cyan-400 animate-pulse" />
                Network Topology
              </div>
              <button onClick={() => setExpanded(false)} className="text-gray-400 hover:text-white w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-700/50">
                <X size={20} />
              </button>
            </div>
            <div style={{ height: 520 }}><TopoSVG full={true} /></div>
            <div className="mt-4 rounded-xl overflow-hidden border border-purple-500/30">
              <img src="/bmn.jpg" alt="Bmn-cx2 Bare Metal Node" className="w-full" />
            </div>
          </div>
        </div>
      )}
    </>
  )
}
