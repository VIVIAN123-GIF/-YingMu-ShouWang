import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

async function loadViewMode(storedValue) {
  vi.resetModules()
  localStorage.clear()
  if (storedValue !== undefined) localStorage.setItem('yingmu-view-mode', storedValue)
  return import('../services/viewMode')
}

describe('双视图模式', () => {
  beforeEach(() => { localStorage.clear() })
  afterEach(() => { vi.resetModules(); localStorage.clear() })

  it('首次打开与无效存储值均回退到家属视图', async () => {
    const initial = await loadViewMode()
    expect(initial.viewModeState.mode).toBe('family')
    const invalid = await loadViewMode('invalid')
    expect(invalid.viewModeState.mode).toBe('family')
  })

  it('切换评审视图并在本机持久保存', async () => {
    const { setViewMode, viewModeState } = await loadViewMode()
    setViewMode('review')
    expect(viewModeState.mode).toBe('review')
    expect(localStorage.getItem('yingmu-view-mode')).toBe('review')
    setViewMode('unknown')
    expect(viewModeState.mode).toBe('review')
  })

  it('家属视图默认折叠技术详情且可手动展开', async () => {
    const { setViewMode } = await import('../services/viewMode')
    const TechnicalDisclosure = (await import('../components/common/TechnicalDisclosure.vue')).default
    setViewMode('family')
    const wrapper = mount(TechnicalDisclosure, { slots: { default: '<div data-testid="details">完整证据</div>' } })
    expect(wrapper.find('[data-testid="details"]').exists()).toBe(false)
    await wrapper.get('button').trigger('click')
    expect(wrapper.text()).toContain('完整证据')
  })

  it('评审视图默认展开技术详情', async () => {
    const { setViewMode } = await import('../services/viewMode')
    const TechnicalDisclosure = (await import('../components/common/TechnicalDisclosure.vue')).default
    setViewMode('review')
    const wrapper = mount(TechnicalDisclosure, { slots: { default: '<div data-testid="details">完整证据</div>' } })
    expect(wrapper.find('[data-testid="details"]').exists()).toBe(true)
    expect(wrapper.find('button').exists()).toBe(false)
    setViewMode('family')
  })
})
