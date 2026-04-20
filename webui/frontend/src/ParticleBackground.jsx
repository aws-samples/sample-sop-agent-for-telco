// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useRef } from 'react'

export default function ParticleBackground() {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    let animId

    const resize = () => { canvas.width = window.innerWidth; canvas.height = window.innerHeight }
    resize()
    window.addEventListener('resize', resize)

    // Hex grid (subtle AWS-style infrastructure pattern)
    const HEX_SIZE = 60
    const drawHexGrid = () => {
      const h = HEX_SIZE * Math.sqrt(3)
      for (let row = -1; row < canvas.height / h + 1; row++) {
        for (let col = -1; col < canvas.width / (HEX_SIZE * 1.5) + 1; col++) {
          const x = col * HEX_SIZE * 1.5
          const y = row * h + (col % 2 ? h / 2 : 0)
          ctx.beginPath()
          for (let i = 0; i < 6; i++) {
            const angle = Math.PI / 3 * i - Math.PI / 6
            const px = x + HEX_SIZE * 0.4 * Math.cos(angle)
            const py = y + HEX_SIZE * 0.4 * Math.sin(angle)
            i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)
          }
          ctx.closePath()
          ctx.strokeStyle = 'rgba(255, 153, 0, 0.03)'
          ctx.lineWidth = 0.5
          ctx.stroke()
        }
      }
    }

    // Floating nodes (representing services/agents)
    const nodes = []
    const NODE_COUNT = 35
    const CONNECT_DIST = 180

    for (let i = 0; i < NODE_COUNT; i++) {
      const isAccent = Math.random() < 0.3
      nodes.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
        r: isAccent ? Math.random() * 2.5 + 1.5 : Math.random() * 1.5 + 0.5,
        // AWS palette: orange accent, teal/slate for others
        color: isAccent ? [255, 153, 0] : Math.random() < 0.5 ? [0, 164, 166] : [100, 140, 180],
        alpha: isAccent ? 0.7 : 0.35,
        pulse: Math.random() * Math.PI * 2,
      })
    }

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      // Subtle radial gradient overlay (dark center, slightly lighter edges)
      const grad = ctx.createRadialGradient(
        canvas.width * 0.3, canvas.height * 0.3, 0,
        canvas.width * 0.5, canvas.height * 0.5, canvas.width * 0.8
      )
      grad.addColorStop(0, 'rgba(255, 153, 0, 0.015)')
      grad.addColorStop(0.5, 'rgba(0, 0, 0, 0)')
      grad.addColorStop(1, 'rgba(0, 164, 166, 0.01)')
      ctx.fillStyle = grad
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      drawHexGrid()

      const time = Date.now() * 0.001

      // Draw connections first (behind nodes)
      for (let i = 0; i < nodes.length; i++) {
        const p = nodes[i]
        for (let j = i + 1; j < nodes.length; j++) {
          const q = nodes[j]
          const dx = p.x - q.x, dy = p.y - q.y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < CONNECT_DIST) {
            const opacity = 0.08 * (1 - dist / CONNECT_DIST)
            // Orange tint for connections between accent nodes
            const isOrange = p.color[0] === 255 || q.color[0] === 255
            ctx.beginPath()
            ctx.moveTo(p.x, p.y)
            ctx.lineTo(q.x, q.y)
            ctx.strokeStyle = isOrange
              ? `rgba(255, 153, 0, ${opacity * 1.5})`
              : `rgba(100, 160, 200, ${opacity})`
            ctx.lineWidth = isOrange ? 0.8 : 0.4
            ctx.stroke()
          }
        }
      }

      // Draw nodes
      for (const p of nodes) {
        p.x += p.vx; p.y += p.vy
        if (p.x < -20) p.x = canvas.width + 20
        if (p.x > canvas.width + 20) p.x = -20
        if (p.y < -20) p.y = canvas.height + 20
        if (p.y > canvas.height + 20) p.y = -20

        const pulseScale = 1 + 0.15 * Math.sin(time * 1.5 + p.pulse)
        const r = p.r * pulseScale

        // Glow
        if (p.r > 1.5) {
          const glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r * 4)
          glow.addColorStop(0, `rgba(${p.color.join(',')}, ${p.alpha * 0.3})`)
          glow.addColorStop(1, `rgba(${p.color.join(',')}, 0)`)
          ctx.fillStyle = glow
          ctx.fillRect(p.x - r * 4, p.y - r * 4, r * 8, r * 8)
        }

        ctx.beginPath()
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${p.color.join(',')}, ${p.alpha})`
        ctx.fill()
      }

      animId = requestAnimationFrame(draw)
    }
    draw()
    return () => { cancelAnimationFrame(animId); window.removeEventListener('resize', resize) }
  }, [])

  return <canvas ref={canvasRef} className="absolute inset-0 pointer-events-none" style={{ zIndex: 0 }} />
}
