import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
  getEvent: vi.fn(),
  getAsset: vi.fn(),
  getSelectedEventMedia: vi.fn(),
}))

vi.mock('../services/repository', () => mocks)

import ReplayView from '../views/ReplayView.vue'

const fraudEvent = {
  schema_version: '1.0',
  event_id: 'event-fraud-structured-only',
  resident_id: 'resident-001',
  created_at: '2026-09-02T09:00:00+08:00',
  updated_at: '2026-09-02T09:10:00+08:00',
  title: '访客身份需要核验',
  primary_domain: 'FRAUD',
  related_domains: [],
  risk_level: 'ORANGE',
  risk_score: 0.79,
  status: 'RESOLVED',
  source_mode: 'RECORDED_REPLAY',
  simulated: true,
  recommended_action: '联系家属核验访客身份。',
  evidence_ids: ['evi-visitor'],
  evidence_summary: [{
    evidence_id: 'evi-visitor',
    evidence_type: 'unauthorized_visitor',
    explanation: '访客未出现在授权名单中。',
  }],
  observations: [],
  rule_traces: [],
  timeline: [],
}

describe('回看页结构化详情', () => {
  it('无视频和时间轴时仍展示风险、证据和干预建议', async () => {
    mocks.getEvents.mockResolvedValue([fraudEvent])
    mocks.getEvent.mockResolvedValue(fraudEvent)
    mocks.getSelectedEventMedia.mockReturnValue(null)

    const wrapper = mount(ReplayView, {
      global: {
        directives: { loading: () => {} },
        stubs: {
          PageHeader: { template: '<header><slot /></header>' },
          ReplaySelector: { template: '<div class="selector-stub" />' },
          RiskBadge: { template: '<span class="risk-stub" />' },
          SourceBadge: { template: '<span class="source-stub" />' },
          'router-link': { template: '<a><slot /></a>' },
          'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
          'el-timeline': { template: '<div><slot /></div>' },
          'el-timeline-item': { template: '<article><slot /></article>' },
          'el-empty': { props: ['description'], template: '<div class="empty-stub">{{ description }}</div>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="replay-metrics"]').text()).toContain('79')
    expect(wrapper.get('[data-testid="replay-evidence-summary"]').text()).toContain('访客未出现在授权名单中')
    expect(wrapper.text()).toContain('联系家属核验访客身份')
    expect(wrapper.text()).toContain('该对照记录没有额外状态流转')
    expect(wrapper.find('.empty-stub').exists()).toBe(false)
    expect(mocks.getAsset).not.toHaveBeenCalled()
  })

  it('详情与视频使用自然高度而非强制等高', () => {
    const cssPath = resolve(process.cwd(), 'src/styles/main.css')
    const css = readFileSync(cssPath, 'utf8')
    expect(css).toContain('[data-testid="replay-view"] .replay-stage { align-items: start; }')
    expect(css).not.toContain('[data-testid="replay-view"] .replay-stage > * { height: 100%')
    expect(css).toContain('[data-testid="event-detail-view"] .event-aside { min-width: 0; height: 100%; }')
  })

  it('高风险事件优先展示干预前的主导因子贡献', async () => {
    const highRiskEvent = {
      ...fraudEvent,
      event_id: 'event-fall-high-risk',
      primary_domain: 'FALL',
      title: '起身后多信号不稳',
      forewarning_snapshots: [
        {
          phase: 'PRE_INTERVENTION',
          dominant_factors: [
            { factor: 'human_instability', contribution: 0.451 },
            { factor: 'human_environment_interaction', contribution: 0.063 },
          ],
        },
        {
          phase: 'POST_INTERVENTION',
          dominant_factors: [{ factor: 'personal_baseline_deviation', contribution: 0.044 }],
        },
      ],
    }
    mocks.getEvents.mockResolvedValue([highRiskEvent])
    mocks.getEvent.mockResolvedValue(highRiskEvent)
    mocks.getSelectedEventMedia.mockReturnValue(null)

    const wrapper = mount(ReplayView, {
      global: {
        directives: { loading: () => {} },
        stubs: {
          PageHeader: { template: '<header><slot /></header>' },
          ReplaySelector: { template: '<div class="selector-stub" />' },
          RiskBadge: { template: '<span class="risk-stub" />' },
          SourceBadge: { template: '<span class="source-stub" />' },
          'router-link': { template: '<a><slot /></a>' },
          'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
          'el-timeline': { template: '<div><slot /></div>' },
          'el-timeline-item': { template: '<article><slot /></article>' },
        },
      },
    })
    await flushPromises()

    const contributions = wrapper.get('[data-testid="replay-factor-contributions"]').text()
    expect(contributions).toContain('人体不稳定')
    expect(contributions).toContain('45%')
    expect(contributions).toContain('人-环境交互')
    expect(contributions).toContain('6%')
    expect(contributions).not.toContain('个人基线偏离')
  })
})
