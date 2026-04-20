// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { useEffect, useRef, useState } from 'react'

export default function AnimatedNumber({ value, decimals = 2, duration = 800 }) {
  const [display, setDisplay] = useState(value)
  const prev = useRef(value)
  const raf = useRef(null)

  useEffect(() => {
    const from = prev.current
    const to = value
    if (from === to) return
    const start = performance.now()

    const animate = (now) => {
      const t = Math.min((now - start) / duration, 1)
      const eased = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t
      setDisplay(from + (to - from) * eased)
      if (t < 1) raf.current = requestAnimationFrame(animate)
      else prev.current = to
    }
    raf.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(raf.current)
  }, [value, duration])

  return <>{display.toFixed(decimals)}</>
}
