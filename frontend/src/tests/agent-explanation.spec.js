import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

const { getAssetMock, getEventMock, getEventExplanationMock, runtimeMock } = vi.hoisted(() => ({
  getAssetMock: vi.fn(),
  getEventMock: vi.fn(),
  getEventExplanationMock: vi.fn(),
  runtimeMock: { mode: 'api' },
}))

vi.mock('../services/repository', () => ({
  getAsset: getAssetMock,
  getEvent: getEventMock,
  getEventExplanation: getEventExplanationMock,
  interveneEvent: vi.fn(),
  runtime: runtimeMock,
  submitInterventionResult: vi.fn(),
}))

import EventDetailView from '../views/EventDetailView.vue'

function eventFixture() {
  return {
    event_id: 'event-agent-test', resident_id: 'resident-001', title: 'Risk event',
    primary_domain: 'FALL', related_domains: [], risk_level: 'ORANGE', risk_score: 0.8,
    status: 'INTERVENING', ruleset_version: 'ruleset-v1.0',
    created_at: '2026-08-16T01:00:00+08:00', updated_at: '2026-08-16T01:00:00+08:00',
    recommended_action: 'Sit safely', intervention_policy: 'fall-orange-gentle-v1',
    time_horizon: 'IMMINENT', evidence_ids: ['evi-1'],
    evidence_summary: [{ evidence_id: 'evi-1', evidence_type: 'rapid_rise', explanation: 'Fast rise' }],
    evidences: [], observations: [], interventions: [], rule_traces: [], timeline: [], risk_history: [],
    source_mode: 'RECORDED_REPLAY', simulated: true,
  }
}

function explanationFixture(status = 'SUCCESS') {
  if (['NOT_REQUESTED', 'PENDING', 'PROCESSING', 'RETRY', 'FAILED'].includes(status)) return {
    event_id: 'event-agent-test', status, request_id: 'agent-test', event_version_hash: null,
    explanation: null, generated_by: null, fallback_used: null, attempt_count: 1,
    error_code: status === 'FAILED' ? 'AGENT_TIMEOUT' : null, created_at: null, completed_at: null,
  }
  const fallback = status === 'FALLBACK'
  return {
    event_id: 'event-agent-test', status, request_id: 'agent-test', event_version_hash: 'v1',
    explanation: {
      schema_version: 'agent-explanation/1.0', request_id: 'agent-test', event_id: 'event-agent-test',
      summary: fallback ? 'Fallback summary' : 'LLM summary', reasoning_points: ['Evidence point'],
      recommended_action_text: 'Sit safely', capability_notice: '萤石服务端语音尚未验证，当前使用Mock语音或文字提醒。',
      generated_by: fallback ? 'template-fallback-v1' : 'qwen3.6-flash', fallback_used: fallback,
    },
    generated_by: fallback ? 'template-fallback-v1' : 'qwen3.6-flash', fallback_used: fallback,
    attempt_count: 1, error_code: null, created_at: null, completed_at: null,
  }
}

async function mountView() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/events/:eventId', component: EventDetailView }] })
  await router.push('/events/event-agent-test')
  await router.isReady()
  const wrapper = mount(EventDetailView, {
    global: {
      plugins: [router], directives: { loading: () => {} },
      stubs: {
        PageHeader: { template: '<header><slot /></header>' }, RiskBadge: { template: '<span />' },
        SourceBadge: { template: '<span />' }, MediaPanel: { template: '<div />' }, ChartPanel: { template: '<div />' },
        'el-alert': { props: ['title'], template: '<div class="alert-stub">{{ title }}</div>' },
        'el-button': { template: '<button><slot /></button>' }, 'el-drawer': { template: '<div><slot /></div>' },
        'el-empty': { props: ['description'], template: '<div>{{ description }}</div>' }, 'el-tag': { template: '<span><slot /></span>' },
        'el-timeline': { template: '<div><slot /></div>' }, 'el-timeline-item': { template: '<div><slot /></div>' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('agent explanation frontend contract', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    getAssetMock.mockReset()
    getEventMock.mockReset()
    getEventExplanationMock.mockReset()
  })

  it('renders SUCCESS and FALLBACK explanations', async () => {
    runtimeMock.mode = 'api'
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock.mockResolvedValue(explanationFixture('FALLBACK'))
    const wrapper = await mountView()

    expect(wrapper.get('[data-testid="agent-explanation-content"]').text()).toContain('Fallback summary')
    expect(wrapper.get('[data-testid="agent-explanation-status"]').text()).toBe('模板降级解释')
    expect(wrapper.get('[data-testid="agent-explanation-generated-by"]').text()).toBe('template-fallback-v1')
    expect(wrapper.get('[data-testid="agent-explanation-fallback-used"]').text()).toBe('true')
    expect(wrapper.get('[data-testid="agent-explanation-fallback"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders explanation completion time in Beijing time', async () => {
    runtimeMock.mode = 'api'
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    const response = explanationFixture('SUCCESS')
    response.completed_at = '2026-08-16T01:30:45Z'
    getEventExplanationMock.mockResolvedValue(response)
    const wrapper = await mountView()

    expect(wrapper.get('[data-testid="agent-explanation-created-at"]').text()).toBe('—')
    expect(wrapper.get('[data-testid="agent-explanation-completed-at"]').text()).toBe('2026/08/16 09:30:45')
    wrapper.unmount()
  })

  it.each([
    ['NOT_REQUESTED', 'agent-explanation-not-requested', '暂无智能体解释'],
    ['PENDING', 'agent-explanation-pending', '解释生成中'],
    ['PROCESSING', 'agent-explanation-pending', '解释生成中'],
    ['RETRY', 'agent-explanation-retry', '解释生成重试中'],
  ])('renders the %s non-terminal state', async (status, testId, copy) => {
    runtimeMock.mode = 'api'
    vi.useFakeTimers()
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock.mockResolvedValue(explanationFixture(status))
    const wrapper = await mountView()

    expect(wrapper.get(`[data-testid="${testId}"]`).text()).toContain(copy)
    expect(wrapper.get('[data-testid="agent-explanation-status"]').text()).toBe(copy)
    wrapper.unmount()
  })

  it('polls every non-terminal status until SUCCESS at 1500ms intervals', async () => {
    runtimeMock.mode = 'api'
    vi.useFakeTimers()
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock
      .mockResolvedValueOnce(explanationFixture('NOT_REQUESTED'))
      .mockResolvedValueOnce(explanationFixture('PENDING'))
      .mockResolvedValueOnce(explanationFixture('PROCESSING'))
      .mockResolvedValueOnce(explanationFixture('RETRY'))
      .mockResolvedValueOnce(explanationFixture('SUCCESS'))
    const wrapper = await mountView()

    expect(wrapper.get('[data-testid="agent-explanation-not-requested"]').exists()).toBe(true)
    for (let count = 2; count <= 5; count += 1) {
      await vi.advanceTimersByTimeAsync(1500)
      await flushPromises()
      expect(getEventExplanationMock).toHaveBeenCalledTimes(count)
    }
    expect(wrapper.get('[data-testid="agent-explanation-content"]').text()).toContain('LLM summary')
    expect(wrapper.get('[data-testid="agent-explanation-generated-by"]').text()).toBe('qwen3.6-flash')
    expect(wrapper.get('[data-testid="agent-explanation-fallback-used"]').text()).toBe('false')

    await vi.advanceTimersByTimeAsync(6000)
    expect(getEventExplanationMock).toHaveBeenCalledTimes(5)
    wrapper.unmount()
  })

  it.each(['SUCCESS', 'FALLBACK', 'FAILED'])('stops polling at terminal status %s', async (status) => {
    runtimeMock.mode = 'api'
    vi.useFakeTimers()
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock.mockResolvedValue(explanationFixture(status))
    const wrapper = await mountView()

    if (status === 'FAILED') {
      expect(wrapper.get('[data-testid="agent-explanation-failed"]').text()).toContain('风险事件与 Evidence 仍正常展示')
      expect(wrapper.text()).toContain('Fast rise')
    }
    await vi.advanceTimersByTimeAsync(6000)
    expect(getEventExplanationMock).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('keeps RiskEvent visible and retries after a temporary explanation request failure', async () => {
    runtimeMock.mode = 'api'
    vi.useFakeTimers()
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock
      .mockRejectedValueOnce(new Error('temporary explanation network error'))
      .mockResolvedValueOnce(explanationFixture('SUCCESS'))
    const wrapper = await mountView()

    expect(wrapper.get('[data-testid="agent-explanation-error"]').text()).toContain('智能体解释暂时读取失败，将自动重试')
    expect(wrapper.text()).not.toContain('temporary explanation network error')
    expect(wrapper.text()).toContain('Risk event')
    expect(wrapper.text()).toContain('Fast rise')

    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(wrapper.get('[data-testid="agent-explanation-content"]').text()).toContain('LLM summary')
    expect(getEventExplanationMock).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('does not overlap explanation requests and clears the next poll on unmount', async () => {
    runtimeMock.mode = 'api'
    vi.useFakeTimers()
    let resolvePending
    const pending = new Promise((resolve) => { resolvePending = resolve })
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock
      .mockResolvedValueOnce(explanationFixture('PENDING'))
      .mockReturnValueOnce(pending)
    const wrapper = await mountView()

    await vi.advanceTimersByTimeAsync(1500)
    await vi.advanceTimersByTimeAsync(6000)
    expect(getEventExplanationMock).toHaveBeenCalledTimes(2)

    resolvePending(explanationFixture('PROCESSING'))
    await flushPromises()
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(6000)
    expect(getEventExplanationMock).toHaveBeenCalledTimes(2)
  })

  it('ignores a stale explanation response after the route changes', async () => {
    runtimeMock.mode = 'api'
    let resolveOldExplanation
    const oldExplanation = new Promise((resolve) => { resolveOldExplanation = resolve })
    const nextExplanation = explanationFixture('SUCCESS')
    nextExplanation.explanation.summary = 'New event summary'
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock
      .mockReturnValueOnce(oldExplanation)
      .mockResolvedValueOnce(nextExplanation)
    const wrapper = await mountView()

    await wrapper.vm.$router.push('/events/event-agent-next')
    await flushPromises()
    expect(getEventExplanationMock).toHaveBeenNthCalledWith(1, 'event-agent-test')
    expect(getEventExplanationMock).toHaveBeenNthCalledWith(2, 'event-agent-next')
    expect(wrapper.get('[data-testid="agent-explanation-content"]').text()).toContain('New event summary')

    const staleExplanation = explanationFixture('SUCCESS')
    staleExplanation.explanation.summary = 'Stale event summary'
    resolveOldExplanation(staleExplanation)
    await flushPromises()
    expect(wrapper.text()).not.toContain('Stale event summary')
    expect(wrapper.get('[data-testid="agent-explanation-content"]').text()).toContain('New event summary')
    wrapper.unmount()
  })

  it('renders RiskEvent immediately without waiting for the explanation request', async () => {
    runtimeMock.mode = 'api'
    let resolveExplanation
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock.mockReturnValue(new Promise((resolve) => { resolveExplanation = resolve }))
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('Risk event')
    expect(wrapper.text()).toContain('Fast rise')
    expect(wrapper.get('[data-testid="agent-explanation-pending"]').text()).toContain('解释生成中')

    wrapper.unmount()
    resolveExplanation(explanationFixture('SUCCESS'))
  })

  it('starts the event and explanation reads independently', async () => {
    runtimeMock.mode = 'api'
    let resolveEvent
    getEventMock.mockReturnValue(new Promise((resolve) => { resolveEvent = resolve }))
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock.mockResolvedValue(explanationFixture('PENDING'))

    const wrapper = await mountView()

    expect(getEventMock).toHaveBeenCalledTimes(1)
    expect(getEventExplanationMock).toHaveBeenCalledTimes(1)
    resolveEvent(eventFixture())
    await flushPromises()
    expect(wrapper.text()).toContain('Risk event')
    wrapper.unmount()
  })

  it('keeps polling the backend explanation in explicit mock mode', async () => {
    runtimeMock.mode = 'replay'
    vi.useFakeTimers()
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock
      .mockResolvedValueOnce(explanationFixture('PENDING'))
      .mockResolvedValueOnce(explanationFixture('SUCCESS'))

    const wrapper = await mountView()
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()

    expect(getEventExplanationMock).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="agent-explanation-content"]').text()).toContain('LLM summary')
    wrapper.unmount()
  })

  it('continues refreshing RiskEvent while the explanation remains PROCESSING', async () => {
    runtimeMock.mode = 'api'
    vi.useFakeTimers()
    const resolvedEvent = {
      ...eventFixture(), status: 'RESOLVED', risk_level: 'GREEN', risk_score: 0.2,
    }
    getEventMock
      .mockResolvedValueOnce(eventFixture())
      .mockResolvedValueOnce(resolvedEvent)
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock
      .mockResolvedValueOnce(explanationFixture('PROCESSING'))
      .mockResolvedValueOnce(explanationFixture('SUCCESS'))
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('正在干预')
    expect(wrapper.get('[data-testid="agent-explanation-pending"]').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()

    expect(wrapper.text()).toContain('已回落')
    expect(wrapper.get('[data-testid="agent-explanation-content"]').text()).toContain('LLM summary')
    expect(getEventMock).toHaveBeenCalledTimes(2)
    expect(getEventExplanationMock).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('does not render sensitive extension fields from the explanation job', async () => {
    runtimeMock.mode = 'api'
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    const response = explanationFixture('SUCCESS')
    Object.assign(response, {
      token: 'secret-token-value',
      file_path: 'C:\\private\\resident\\recording.wav',
      device_serial: 'DEVICE-SERIAL-001',
      temporary_url: 'https://temporary.example.test/private-stream',
      raw_transcript: 'raw-private-transcript',
    })
    Object.assign(response.explanation, {
      token: 'nested-secret-token',
      raw_transcript: 'nested-private-transcript',
    })
    getEventExplanationMock.mockResolvedValue(response)
    const wrapper = await mountView()
    const rendered = wrapper.text()

    expect(rendered).not.toContain('secret-token-value')
    expect(rendered).not.toContain('C:\\private\\resident\\recording.wav')
    expect(rendered).not.toContain('DEVICE-SERIAL-001')
    expect(rendered).not.toContain('https://temporary.example.test/private-stream')
    expect(rendered).not.toContain('raw-private-transcript')
    expect(rendered).not.toContain('nested-secret-token')
    expect(rendered).not.toContain('nested-private-transcript')
    wrapper.unmount()
  })
})
