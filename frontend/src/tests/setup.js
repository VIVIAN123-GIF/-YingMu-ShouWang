import { afterEach, vi } from 'vitest'
import { config } from '@vue/test-utils'

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock
globalThis.matchMedia = globalThis.matchMedia || (() => ({
  matches: false,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
}))

config.global.stubs = {
  transition: false,
  'el-tag': { template: '<span class="el-tag-stub"><slot /></span>' },
}

afterEach(() => {
  sessionStorage.clear()
  vi.restoreAllMocks()
})
