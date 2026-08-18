// ResizeObserver polyfill for recharts ResponsiveContainer
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}


import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Ant Design and some hooks rely on matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// rc-table / Ant Design Table: jsdom's getComputedStyle is incomplete for pseudo-elements
window.getComputedStyle = (elt, _pseudo) => ({
  getPropertyValue: () => '',
  width: '100px',
})

afterEach(() => {
  cleanup()
})
