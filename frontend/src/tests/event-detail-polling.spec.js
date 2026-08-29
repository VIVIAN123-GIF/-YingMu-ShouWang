import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { getAssetMock, getEventMock, getEventExplanationMock, interveneEventMock, runtimeMock, submitInterventionResultMock } = vi.hoisted(() => ({
  getAssetMock: vi.fn(),
  getEventMock: vi.fn(),
  getEventExplanationMock: vi.fn(),
  interveneEventMock: vi.fn(),
  runtimeMock: { mode: 'api' },
  submitInterventionResultMock: vi.fn(),
}))

vi.mock('../services/repository', () => ({
  getAsset: getAssetMock,
  getEvent: getEventMock,
  getEventExplanation: getEventExplanationMock,
  interveneEvent: interveneEventMock,
  runtime: runtimeMock,
  submitInterventionResult: submitInterventionResultMock,
}))

import EventDetailView from '../views/EventDetailView.vue'

function apiEvent(status, { eventId = 'event-poll-1', assetId = 'asset-poll-1' } = {}) {
  const timeByStatus = {
    INTERVENING: '2026-07-31T03:07:05+08:00',
    OBSERVING: '2026-07-31T03:07:29+08:00',
    RESOLVED: '2026-07-31T03:08:30+08:00',
    FALSE_ALARM: '2026-07-31T03:08:30+08:00',
  }
  return {
    event_id: eventId,
    resident_id: 'resident-api',
    title: '快速起身后出现明显躯干摇晃',
    primary_domain: 'FALL',
    risk_level: status === 'RESOLVED' ? 'GREEN' : 'ORANGE',
    risk_score: status === 'RESOLVED' ? 0.24 : 0.82,
    status,
    ruleset_version: 'ruleset-v1.0',
    created_at: '2026-07-31T03:07:05+08:00',
    updated_at: timeByStatus[status],
    recommended_action: '请先坐稳',
    source_mode: 'RECORDED_REPLAY',
    simulated: true,
    evidence_summary: [{ evidence_id: 'evi-1', evidence_type: 'rapid_rise', explanation: '快速起身' }],
    evidences: [{
      evidence_id: 'evi-1', observation_ids: ['obs-1'], evidence_type: 'rapid_rise', explanation: '快速起身',
      severity: 0.8, confidence: 0.9, data_quality: 0.9, source_mode: 'RECORDED_REPLAY', simulated: true,
    }],
    observations: [{ observation_id: 'obs-1', asset_id: assetId, feature_name: 'rise_duration' }],
    interventions: [],
    rule_traces: [{
      event_id: eventId, evaluated_at: timeByStatus[status], matched_rule: 'R-FALL-01',
      previous_status: status === 'INTERVENING' ? 'OPEN' : 'INTERVENING', next_status: status,
    }],
    timeline: [],
    risk_history: [],
  }
}

async function mountView(path = '/events/event-poll-1') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/events/:eventId', component: EventDetailView }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(EventDetailView, {
    global: {
      plugins: [router],
      directives: { loading: () => {} },
      stubs: {
        PageHeader: { template: '<header><slot /></header>' },
        RiskBadge: { template: '<span />' },
        SourceBadge: { template: '<span />' },
        ChartPanel: { template: '<div />' },
        'el-alert': { props: ['title'], template: '<div class="alert-stub">{{ title }}</div>' },
        'el-button': { template: '<button><slot /></button>' },
        'el-drawer': { template: '<div><slot /></div>' },
        'el-empty': { props: ['description'], template: '<div>{{ description }}</div>' },
        'el-tag': { template: '<span><slot /></span>' },
        'el-timeline': { template: '<div><slot /></div>' },
        'el-timeline-item': { template: '<div><slot /></div>' },
      },
    },
  })
  await flushPromises()
  return { router, wrapper }
}

describe('事件详情 API 自动同步', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    runtimeMock.mode = 'api'
    getAssetMock.mockReset()
    getAssetMock.mockResolvedValue({
      asset_id: 'asset-poll-1', title: '测试素材', source_mode: 'RECORDED_REPLAY', simulated: true,
      stream_url: null, fallback_url: null, notice: '暂无文件', captured_at: '2026-07-31T03:07:05+08:00',
    })
    getEventMock.mockReset()
    getEventExplanationMock.mockReset()
    getEventExplanationMock.mockResolvedValue({
      event_id: 'event-poll-1', status: 'SUCCESS', request_id: 'agent-event-poll-1',
      event_version_hash: 'version-1', generated_by: 'mock-agent-v1', fallback_used: false,
      attempt_count: 1, error_code: null, created_at: null, completed_at: null,
      explanation: {
        schema_version: 'agent-explanation/1.0', request_id: 'agent-event-poll-1', event_id: 'event-poll-1',
        summary: '已完成风险解释', reasoning_points: ['检测到快速起身'],
        recommended_action_text: '请先坐稳', capability_notice: '使用模拟能力', generated_by: 'mock-agent-v1', fallback_used: false,
      },
    })
    submitInterventionResultMock.mockReset()
    interveneEventMock.mockReset()
  })

  afterEach(() => vi.useRealTimers())

  it('自动显示干预、观察和回落，并在终态停止且不重复请求404素材', async () => {
    const notFound = Object.assign(new Error('authorized asset does not exist'), {
      response: { status: 404 }, api: { code: 'ASSET_NOT_FOUND' },
    })
    getAssetMock.mockRejectedValue(notFound)
    getEventMock
      .mockResolvedValueOnce(apiEvent('INTERVENING'))
      .mockResolvedValueOnce(apiEvent('OBSERVING'))
      .mockResolvedValueOnce(apiEvent('RESOLVED'))
    const { wrapper } = await mountView()

    expect(wrapper.text()).toContain('正在干预')
    expect(wrapper.text()).toContain('后端暂无素材记录（asset-poll-1）')
    expect(wrapper.get('[data-testid="event-sync-status"]').text()).toBe('自动同步中')
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(wrapper.text()).toContain('观察期')
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(wrapper.text()).toContain('已回落')
    expect(wrapper.get('[data-testid="event-sync-status"]').text()).toBe('同步已完成')

    await vi.advanceTimersByTimeAsync(6000)
    expect(getEventMock).toHaveBeenCalledTimes(3)
    expect(getAssetMock).toHaveBeenCalledTimes(1)
    expect(getAssetMock).toHaveBeenCalledWith('asset-poll-1')
    wrapper.unmount()
  })

  it('后台请求失败时保留有效内容并在下一轮恢复', async () => {
    getEventMock
      .mockResolvedValueOnce(apiEvent('INTERVENING'))
      .mockRejectedValueOnce(new Error('temporary network error'))
      .mockResolvedValueOnce(apiEvent('RESOLVED'))
    const { wrapper } = await mountView()

    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(wrapper.text()).toContain('正在干预')
    expect(wrapper.text()).toContain('自动同步暂时失败，将继续重试')
    expect(wrapper.get('[data-testid="event-sync-status"]').text()).toBe('同步重试中')

    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(wrapper.text()).toContain('已回落')
    expect(wrapper.text()).not.toContain('自动同步暂时失败')
    wrapper.unmount()
  })

  it('误报状态作为终态展示并停止轮询', async () => {
    getEventMock.mockResolvedValueOnce(apiEvent('FALSE_ALARM', { assetId: null }))
    const { wrapper } = await mountView()

    expect(wrapper.text()).toContain('已确认误报')
    expect(wrapper.get('[data-testid="event-sync-status"]').text()).toBe('同步已完成')
    await vi.advanceTimersByTimeAsync(6000)
    expect(getEventMock).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('没有依据、工具记录和时间轴时不渲染空卡片', async () => {
    const current = apiEvent('RESOLVED')
    Object.assign(current, {
      primary_domain: 'MENTAL',
      evidence_summary: [],
      evidences: [],
      observations: [],
      interventions: [],
      rule_traces: [],
      timeline: [],
      risk_history: [],
    })
    getEventMock.mockResolvedValueOnce(current)
    const { wrapper } = await mountView()

    expect(wrapper.find('[data-testid="evidence-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="intervention-result-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="event-action-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="event-detail-grid"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('等待当前请求结束后才安排下一轮，不产生重叠请求', async () => {
    let resolvePending
    const pending = new Promise((resolve) => { resolvePending = resolve })
    getEventMock
      .mockResolvedValueOnce(apiEvent('INTERVENING'))
      .mockReturnValueOnce(pending)
      .mockResolvedValueOnce(apiEvent('RESOLVED'))
    const { wrapper } = await mountView()

    await vi.advanceTimersByTimeAsync(1500)
    await vi.advanceTimersByTimeAsync(6000)
    expect(getEventMock).toHaveBeenCalledTimes(2)

    resolvePending(apiEvent('OBSERVING'))
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(getEventMock).toHaveBeenCalledTimes(3)
    wrapper.unmount()
  })

  it('切换事件会忽略旧会话，组件卸载后清除轮询', async () => {
    getEventMock
      .mockResolvedValueOnce(apiEvent('INTERVENING'))
      .mockResolvedValueOnce(apiEvent('RESOLVED', { eventId: 'event-poll-2', assetId: null }))
    const { router, wrapper } = await mountView()

    await router.push('/events/event-poll-2')
    await flushPromises()
    expect(wrapper.text()).toContain('event-poll-2')
    expect(getEventMock).toHaveBeenCalledTimes(2)

    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(6000)
    expect(getEventMock).toHaveBeenCalledTimes(2)
  })

  it('坐稳确认只回写 InterventionResult，不在前端直接关闭事件', async () => {
    const current = apiEvent('INTERVENING')
    getEventMock.mockResolvedValueOnce(current)
    submitInterventionResultMock.mockResolvedValueOnce({
      schema_version: '1.0',
      result_id: 'result-stable-1',
      event_id: current.event_id,
      started_at: '2026-07-31T03:07:10+08:00',
      completed_at: '2026-07-31T03:07:10+08:00',
      action_type: 'resident_response',
      tool_name: 'family_console',
      delivery_status: 'SUCCESS',
      resident_response: 'stable',
      family_feedback: null,
      risk_after: null,
      resolved: false,
      resolution_reason: null,
      operator: 'family',
      source_mode: 'RECORDED_REPLAY',
      simulated: true,
    })
    const { wrapper } = await mountView()

    await wrapper.get('[data-testid="elder-stable-submit"]').trigger('click')
    await flushPromises()

    expect(submitInterventionResultMock).toHaveBeenCalledWith(current, 'stable')
    expect(wrapper.text()).toContain('坐稳确认已记录')
    expect(wrapper.text()).toContain('正在干预')
    expect(wrapper.text()).toContain('不会直接关闭事件')
    wrapper.unmount()
  })

  it('发起干预只调用后端干预动作并展示返回的工具结果', async () => {
    const current = apiEvent('INTERVENING')
    getEventMock.mockResolvedValueOnce(current)
    interveneEventMock.mockResolvedValueOnce({
      schema_version: '1.0', result_id: 'result-intervene-1', event_id: current.event_id,
      started_at: '2026-07-31T03:07:10+08:00', completed_at: '2026-07-31T03:07:10+08:00',
      action_type: 'voice', tool_name: 'mock_voice', delivery_status: 'SUCCESS', resident_response: null,
      family_feedback: null, risk_after: null, resolved: false, resolution_reason: 'Declared Mock fallback',
      operator: 'system', source_mode: 'RECORDED_REPLAY', simulated: true,
    })
    const { wrapper } = await mountView()

    await wrapper.get('[data-testid="intervention-submit"]').trigger('click')
    await flushPromises()

    expect(interveneEventMock).toHaveBeenCalledWith(current.event_id)
    expect(submitInterventionResultMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('干预请求已提交')
    expect(wrapper.text()).toContain('mock_voice')
    expect(wrapper.text()).toContain('正在干预')
    wrapper.unmount()
  })
})
