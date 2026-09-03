import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { getAssetMock, getEventMock, getEventExplanationMock, getSelectedEventMediaMock, interveneEventMock, runtimeMock, submitInterventionResultMock } = vi.hoisted(() => ({
  getAssetMock: vi.fn(),
  getEventMock: vi.fn(),
  getEventExplanationMock: vi.fn(),
  getSelectedEventMediaMock: vi.fn(() => null),
  interveneEventMock: vi.fn(),
  runtimeMock: { mode: 'api' },
  submitInterventionResultMock: vi.fn(),
}))

vi.mock('../services/repository', () => ({
  getAsset: getAssetMock,
  getEvent: getEventMock,
  getEventExplanation: getEventExplanationMock,
  getSelectedEventMedia: getSelectedEventMediaMock,
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
    getSelectedEventMediaMock.mockReset()
    getSelectedEventMediaMock.mockReturnValue(null)
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
    expect(wrapper.text()).toContain('素材暂不可用（asset-poll-1）')
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
    expect(wrapper.text()).toContain('事件记录 2')
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
    expect(wrapper.text()).toContain('2026/07/31 03:07:10')
    expect(wrapper.text()).toContain('确认后仍将继续观察事件状态')
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
    expect(wrapper.text()).toContain('处理请求已提交')
    expect(wrapper.text()).toContain('本地语音提醒')
    expect(wrapper.text()).toContain('已使用备用提醒流程')
    expect(wrapper.text()).toContain('正在干预')
    wrapper.unmount()
  })

  it('刷新后从已有干预结果恢复坐稳确认，且不再重复提交', async () => {
    const current = apiEvent('INTERVENING')
    current.interventions.push({
      schema_version: '1.0', result_id: 'result-stable-existing', event_id: current.event_id,
      started_at: '2026-07-31T03:07:10+08:00', completed_at: '2026-07-31T03:07:10+08:00',
      action_type: 'resident_response', tool_name: 'family_console', delivery_status: 'SUCCESS',
      resident_response: 'stable', family_feedback: null, risk_after: null, resolved: false,
      resolution_reason: null, operator: 'family', source_mode: 'RECORDED_REPLAY', simulated: true,
    })
    getEventMock.mockResolvedValueOnce(current)
    const { wrapper } = await mountView()

    const button = wrapper.get('[data-testid="elder-stable-submit"]')
    expect(button.text()).toContain('坐稳确认已记录')
    expect(button.attributes('disabled')).toBeDefined()
    await button.trigger('click')
    expect(submitInterventionResultMock).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('刷新后从已有工具结果恢复处理请求状态，且不重复发起干预', async () => {
    const current = apiEvent('INTERVENING')
    current.interventions.push({
      schema_version: '1.0', result_id: 'result-voice-existing', event_id: current.event_id,
      started_at: '2026-07-31T03:07:08+08:00', completed_at: null,
      action_type: 'voice', tool_name: 'mock_voice', delivery_status: 'RETRYING', resident_response: null,
      family_feedback: null, risk_after: null, resolved: false, resolution_reason: null,
      operator: 'system', source_mode: 'RECORDED_REPLAY', simulated: true,
    })
    getEventMock.mockResolvedValueOnce(current)
    const { wrapper } = await mountView()

    const button = wrapper.get('[data-testid="intervention-submit"]')
    expect(button.text()).toContain('处理请求已提交')
    expect(button.attributes('disabled')).toBeDefined()
    await button.trigger('click')
    expect(interveneEventMock).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('坐稳确认失败时在按钮下方持续显示错误', async () => {
    const current = apiEvent('INTERVENING')
    getEventMock.mockResolvedValueOnce(current)
    submitInterventionResultMock.mockRejectedValueOnce(new Error('结果 ID 冲突'))
    const { wrapper } = await mountView()

    await wrapper.get('[data-testid="elder-stable-submit"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('确认提交失败：结果 ID 冲突')
    expect(wrapper.get('[data-testid="elder-stable-submit"]').text()).toContain('我已坐稳')
    wrapper.unmount()
  })

  it('默认加载受控主片，切换相关片段时只更新播放器素材与片段说明', async () => {
    const current = apiEvent('RESOLVED')
    getSelectedEventMediaMock.mockReturnValue({
      primary_asset_id: 'selected-p01-golden-loop-01',
      entries: [
        { asset_id: 'selected-p01-golden-loop-01', clip_id: 'p01-golden-loop-01', participant_id: 'P01', scenario: '黄金闭环', purpose: '高风险工程对照', sha256_short: 'abc123', is_primary: true },
        { asset_id: 'selected-p02-golden-loop-01', clip_id: 'p02-golden-loop-01', participant_id: 'P02', scenario: '黄金闭环', purpose: '高风险工程对照', sha256_short: 'ghi789', is_primary: false },
        { asset_id: 'selected-qg-01', clip_id: 'qg-01', participant_id: 'QG-01', scenario: '质量门控', purpose: '质量边界对照', sha256_short: 'def456', is_primary: false },
      ],
    })
    getAssetMock.mockImplementation((assetId) => Promise.resolve({
      asset_id: assetId, title: assetId, source_mode: 'RECORDED_REPLAY', simulated: true,
      stream_url: null, fallback_url: `/media/selected/${assetId}.mp4`, notice: 'controlled comparison', captured_at: '2026-08-27T09:00:00+08:00',
    }))
    getEventMock.mockResolvedValueOnce(current)
    const { wrapper } = await mountView()

    expect(getAssetMock).toHaveBeenCalledWith('selected-p01-golden-loop-01')
    expect(wrapper.find('[data-testid="related-media-selector"]').exists()).toBe(false)
    await wrapper.get('[aria-label="查看验证对照片段"] .technical-disclosure-trigger').trigger('click')
    expect(wrapper.get('[data-testid="related-media-selector"]').text()).toContain('受控工程对照')
    expect(wrapper.findAll('.related-media-option')).toHaveLength(2)
    expect(wrapper.find('[data-testid="related-media-p02-golden-loop-01"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="selected-media-meta"]').text()).toContain('P01')
    const scoreBefore = wrapper.get('.event-score').text()
    await wrapper.get('[data-testid="related-media-qg-01"]').trigger('click')
    await flushPromises()
    expect(getAssetMock).toHaveBeenCalledWith('selected-qg-01')
    expect(wrapper.get('[data-testid="selected-media-meta"]').text()).toContain('QG-01')
    expect(wrapper.get('.event-score').text()).toBe(scoreBefore)
    expect(wrapper.text()).toContain('不会改动当前事件的风险等级')
    wrapper.unmount()
  })

  it('展示前置预警主导因子贡献及其关联依据', async () => {
    const current = apiEvent('INTERVENING')
    current.forewarning_snapshots = [{
      schema_version: 'forewarning-snapshot/1.0', snapshot_id: 'snapshot-factor-1', resident_id: current.resident_id,
      evaluated_at: '2026-07-31T03:07:05+08:00', phase: 'PRE_INTERVENTION', assessment_status: 'VALID',
      confidence_level: 'HIGH', baseline_status: 'STABLE',
      components: { human_risk: 0.82, personal_deviation: 0.61, environment_risk: 0.18, interaction_risk: 0.42 },
      instant: { window_seconds: 8, engineering_index: 0.78, attention_level: 'ORANGE' },
      short_30s: { window_seconds: 30, engineering_index: 0.72, attention_level: 'ORANGE' },
      trend_3min: { window_seconds: 180, engineering_index: 0.64, attention_level: 'YELLOW' },
      degradation_reasons: [],
      dominant_factors: [
        { factor: 'human_instability', contribution: 0.451, evidence_ids: ['evi-1'] },
        { factor: 'human_environment_interaction', contribution: 0.063, evidence_ids: ['evi-light-1'] },
      ],
      recommended_action: '先坐稳', ruleset_version: 'ruleset-v1.3-min', source_mode: 'RECORDED_REPLAY', simulated: true,
    }]
    getEventMock.mockResolvedValueOnce(current)
    const { wrapper } = await mountView()

    const panel = wrapper.get('[data-testid="forewarning-factor-contributions"]')
    expect(panel.text()).toContain('人体不稳定')
    expect(panel.text()).toContain('贡献 45%')
    expect(panel.text()).toContain('关联依据：1 条')
    expect(panel.text()).toContain('人-环境交互')
    expect(panel.text()).toContain('贡献 6%')
    wrapper.unmount()
  })
})
