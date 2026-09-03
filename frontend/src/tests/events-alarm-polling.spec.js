import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { getAlarmProcessingTasksMock, getEventsMock, getRiskReviewsMock, runtimeMock } = vi.hoisted(() => ({
  getAlarmProcessingTasksMock: vi.fn(), getEventsMock: vi.fn(), getRiskReviewsMock: vi.fn(), runtimeMock: { mode: 'api' },
}))

vi.mock('../services/repository', () => ({
  getAlarmProcessingTasks: getAlarmProcessingTasksMock,
  getEvents: getEventsMock,
  getRiskReviews: getRiskReviewsMock,
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

const reviewItem = {
  trace_id: 'trace-review-1', evidence_type: 'assessment_indeterminate',
  explanation: '观察窗口不完整，需要人工复核', evaluated_at: '2026-08-26T10:00:00+08:00',
  matched_rule: 'R-FALL-09', ruleset_version: 'ruleset-v1.2', risk_level: 'UNKNOWN',
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
    getRiskReviewsMock.mockReset().mockResolvedValue([reviewItem])
    getAlarmProcessingTasksMock.mockReset().mockResolvedValue([waitingTask])
  })
  afterEach(() => { vi.useRealTimers() })

  it('使用 resident_id 和 limit=20，每 2000ms 轮询，并在卸载后停止', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(getAlarmProcessingTasksMock).toHaveBeenCalledWith({ residentId: 'resident-001', limit: 20 })
    expect(wrapper.text()).toContain('工程复核与设备任务')
    expect(wrapper.text()).not.toContain('等待算法分析')
    await wrapper.get('.technical-disclosure-trigger').trigger('click')
    expect(wrapper.text()).toContain('等待算法分析')
    expect(wrapper.text()).toContain('本次评估不可判定')
    expect(wrapper.text()).toContain('风险判断规则 09')
    expect(wrapper.text()).not.toContain('检测到跌倒')
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(getAlarmProcessingTasksMock).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(10000)
    expect(getAlarmProcessingTasksMock).toHaveBeenCalledTimes(2)
  })

  it('把最新 LIVE_DEVICE / simulated=false 事件置顶到回放事件之前', async () => {
    getEventsMock.mockResolvedValue([
      { event_id: 'event-replay-newer', title: '回放事件', primary_domain: 'FALL', risk_level: 'ORANGE', risk_score: 0.8, status: 'OPEN', recommended_action: '回放', ruleset_version: 'ruleset-v1.5', source_mode: 'RECORDED_REPLAY', simulated: true, created_at: '2026-09-02T10:05:00+08:00' },
      { event_id: 'event-live-latest', title: '真实事件', primary_domain: 'FALL', risk_level: 'ORANGE', risk_score: 0.82, status: 'OPEN', recommended_action: '现场', ruleset_version: 'ruleset-v1.5', source_mode: 'LIVE_DEVICE', simulated: false, created_at: '2026-09-02T10:00:00+08:00' },
    ])
    const wrapper = mountView(); await flushPromises()
    const rows = wrapper.findAll('.unified-event')
    expect(rows[0].text()).toContain('真实事件')
    expect(rows[0].text()).toContain('最新真实运行')
    expect(rows[1].text()).toContain('回放事件')
    wrapper.unmount()
  })
})
