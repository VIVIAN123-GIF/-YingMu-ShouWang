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
    source_mode: 'MOCK', simulated: true,
  }
}

function explanationFixture(status = 'SUCCESS') {
  if (status === 'PROCESSING') return {
    event_id: 'event-agent-test', status, request_id: 'agent-test', event_version_hash: null,
    explanation: null, generated_by: null, fallback_used: null, attempt_count: 1,
    error_code: null, created_at: null, completed_at: null,
  }
  const fallback = status === 'FALLBACK'
  return {
    event_id: 'event-agent-test', status, request_id: 'agent-test', event_version_hash: 'v1',
    explanation: {
      schema_version: 'agent-explanation/1.0', request_id: 'agent-test', event_id: 'event-agent-test',
      summary: fallback ? 'Fallback summary' : 'LLM summary', reasoning_points: ['Evidence point'],
      recommended_action_text: 'Sit safely', capability_notice: 'Mock notice',
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
    expect(wrapper.get('[data-testid="agent-explanation-fallback"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows pending status and polls until SUCCESS', async () => {
    runtimeMock.mode = 'api'
    vi.useFakeTimers()
    getEventMock.mockResolvedValue(eventFixture())
    getAssetMock.mockResolvedValue(null)
    getEventExplanationMock
      .mockResolvedValueOnce(explanationFixture('PROCESSING'))
      .mockResolvedValueOnce(explanationFixture('SUCCESS'))
    const wrapper = await mountView()

    expect(wrapper.get('[data-testid="agent-explanation-pending"]').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(wrapper.get('[data-testid="agent-explanation-content"]').text()).toContain('LLM summary')
    expect(getEventMock).toHaveBeenCalled()
    wrapper.unmount()
  })
})
