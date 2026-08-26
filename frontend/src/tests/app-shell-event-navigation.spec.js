import { flushPromises, shallowMount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getEventsMock, messageMock, setDataModeMock, runtimeMock } = vi.hoisted(() => ({
  getEventsMock: vi.fn(),
  messageMock: { info: vi.fn(), error: vi.fn() },
  setDataModeMock: vi.fn(),
  runtimeMock: {
    mode: 'api', activeSource: 'api', degraded: false, message: '',
  },
}))

vi.mock('../services/repository', () => ({
  getEvents: getEventsMock,
  runtime: runtimeMock,
  setDataMode: setDataModeMock,
}))

vi.mock('element-plus', async (importOriginal) => ({
  ...(await importOriginal()),
  ElMessage: messageMock,
}))

import AppShell from '../components/layout/AppShell.vue'

const ViewStub = { template: '<div />' }

async function mountShell(path = '/') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: ViewStub },
      { path: '/events', name: 'events', component: ViewStub },
      { path: '/events/detail', name: 'event-detail-empty', component: ViewStub },
      { path: '/events/:eventId', name: 'event-detail', component: ViewStub },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = shallowMount(AppShell, { global: { plugins: [router] } })
  return { router, wrapper }
}

describe('风险事件详情导航入口', () => {
  beforeEach(() => {
    getEventsMock.mockReset()
    messageMock.info.mockReset()
    messageMock.error.mockReset()
  })

  it('读取后端事件列表并进入创建时间最新的真实事件', async () => {
    getEventsMock.mockResolvedValue([
      { event_id: 'event-old', created_at: '2026-08-15T10:00:00+08:00' },
      { event_id: 'event latest/一', created_at: '2026-08-16T10:00:00+08:00' },
    ])
    const { router, wrapper } = await mountShell()

    await wrapper.vm.handleSelect('/events/:eventId')
    await flushPromises()

    expect(getEventsMock).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.name).toBe('event-detail')
    expect(router.currentRoute.value.params.eventId).toBe('event latest/一')
    expect(router.currentRoute.value.fullPath).toContain('event%20latest%2F')
  })

  it('调取事件列表期间显示加载状态', async () => {
    let resolveEvents
    getEventsMock.mockReturnValue(new Promise((resolve) => { resolveEvents = resolve }))
    const { wrapper } = await mountShell()

    const navigation = wrapper.vm.handleSelect('/events/:eventId')
    await wrapper.vm.$nextTick()

    expect(wrapper.vm.openingEventDetail).toBe(true)
    expect(wrapper.get('[data-testid="event-navigation-loading"]').attributes('element-loading-text')).toBe('正在调取风险事件')

    resolveEvents([])
    await navigation
    expect(wrapper.vm.openingEventDetail).toBe(false)
  })

  it('已经位于事件详情页时保留当前事件且不重复读取列表', async () => {
    const { router, wrapper } = await mountShell('/events/event-current')

    await wrapper.vm.handleSelect('/events/:eventId')

    expect(getEventsMock).not.toHaveBeenCalled()
    expect(router.currentRoute.value.params.eventId).toBe('event-current')
  })

  it('没有事件时进入详情失败状态并显示调取失败', async () => {
    getEventsMock.mockResolvedValue([])
    const { router, wrapper } = await mountShell()

    await wrapper.vm.handleSelect('/events/:eventId')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('event-detail-empty')
    expect(router.currentRoute.value.path).toBe('/events/detail')
    expect(messageMock.error).toHaveBeenCalledWith('风险事件调取失败：当前居民暂无可用事件')
  })

  it('事件列表请求失败时不进入错误详情地址', async () => {
    getEventsMock.mockRejectedValue(new Error('private backend detail'))
    const { router, wrapper } = await mountShell()

    await wrapper.vm.handleSelect('/events/:eventId')

    expect(router.currentRoute.value.name).toBe('event-detail-empty')
    expect(router.currentRoute.value.query.reason).toBe('unavailable')
    expect(messageMock.error).toHaveBeenCalledWith('风险事件调取失败：FastAPI 服务不可达')
    expect(messageMock.error.mock.calls[0][0]).not.toContain('private backend detail')
  })
})
