import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { getAlarmProcessingTasksMock, getEventsMock, runtimeMock } = vi.hoisted(() => ({
  getAlarmProcessingTasksMock: vi.fn(), getEventsMock: vi.fn(), runtimeMock: { mode: 'api' },
}))

vi.mock('../services/repository', () => ({
  getAlarmProcessingTasks: getAlarmProcessingTasksMock,
  getEvents: getEventsMock,
  RESIDENT_ID: 'resident-001',
  runtime: runtimeMock,
}))

import EventsView from '../views/EventsView.vue'

const waitingTask = {
  task_id: 'alarm-task-1', alarm_ref: 'alarm-1', resident_id: 'resident-001', device_ref: 'device-1',
  status: 'WAITING_ALGORITHM', attempt_count: 1, max_attempts: 3, capture_asset_id: 'asset-1',
  error_code: null, error_message: null, available_at: '2026-08-11T15:00:00',
  started_at: '2026-08-11T15:00:01', finished_at: null, create_time: '2026-08-11T15:00:00', update_time: '2026-08-11T15:00:01',
}

function mountView() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  return mount(EventsView, { global: { plugins: [router], directives: { loading: () => {} }, stubs: {
    PageHeader: { template: '<header><slot /></header>' }, RiskBadge: { template: '<span />' }, SourceBadge: { template: '<span />' },
    'el-tag': { template: '<span><slot /></span>' }, 'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
    'el-empty': { props: ['description'], template: '<div>{{ description }}</div>' }, 'el-select': { template: '<div><slot /></div>' },
    'el-option': { template: '<div />' }, 'el-button': { template: '<button><slot /></button>' },
  } } })
}

describe('告警处理任务轮询', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    runtimeMock.mode = 'api'
    getEventsMock.mockReset().mockResolvedValue([])
    getAlarmProcessingTasksMock.mockReset().mockResolvedValue([waitingTask])
  })
  afterEach(() => vi.useRealTimers())

  it('使用 resident_id 和 limit=20，每 5000ms 轮询，并在卸载后停止', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(getAlarmProcessingTasksMock).toHaveBeenCalledWith({ residentId: 'resident-001', limit: 20 })
    expect(wrapper.text()).toContain('等待算法分析')
    expect(wrapper.text()).not.toContain('检测到跌倒')
    await vi.advanceTimersByTimeAsync(5000)
    await flushPromises()
    expect(getAlarmProcessingTasksMock).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(10000)
    expect(getAlarmProcessingTasksMock).toHaveBeenCalledTimes(2)
  })
})
