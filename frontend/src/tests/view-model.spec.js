import { describe, expect, it } from 'vitest'
import {
  deriveEventTitle, normalizeBaseline, normalizeDashboard, normalizeDevice, normalizeEvent,
  normalizeWeeklyReport,
} from '../services/viewModel'

const apiEvent = {
  event_id: 'event-api-001',
  resident_id: 'resident-api',
  primary_domain: 'FALL',
  evidence_ids: ['evi-rise', 'evi-recovered'],
  evidence_summary: [
    { evidence_id: 'evi-rise', evidence_type: 'rapid_rise', explanation: '起身速度明显快于个人基线' },
  ],
  rule_traces: [
    { event_id: 'event-api-001', evidence_id: 'evi-rise', evaluated_at: '2026-07-31T03:07:28+08:00', matched_rule: 'R-FALL-02', previous_state: 'GREEN', next_state: 'ORANGE', next_status: 'INTERVENING' },
    { event_id: 'event-api-001', evidence_id: 'evi-recovered', evaluated_at: '2026-07-31T03:07:29+08:00', matched_rule: 'R-FALL-04', previous_status: 'INTERVENING', next_status: 'OBSERVING' },
    { event_id: 'event-api-001', evidence_id: null, evaluated_at: '2026-07-31T03:08:30+08:00', matched_rule: 'R-FALL-05', previous_status: 'OBSERVING', next_status: 'RESOLVED' },
    { event_id: 'other-event', evidence_id: 'other', evaluated_at: '2026-07-31T03:09:00+08:00', matched_rule: 'OTHER', next_status: 'OPEN' },
  ],
  interventions: [{
    result_id: 'feedback-1', event_id: 'event-api-001', started_at: '2026-07-31T03:08:31+08:00',
    completed_at: '2026-07-31T03:08:31+08:00', tool_name: 'family_feedback',
    delivery_status: 'SUCCESS', family_feedback: '已联系，近期一切正常',
  }],
}

describe('API ViewModel 适配', () => {
  it('用真实摘要生成标题并映射回落时间轴，不伪造风险分', () => {
    const event = normalizeEvent(apiEvent)
    expect(deriveEventTitle(apiEvent)).toBe('起身速度明显快于个人基线')
    expect(event.rule_traces).toHaveLength(3)
    expect(event.timeline.map((item) => item.status)).toEqual([
      'INTERVENING', 'OBSERVING', 'RESOLVED', 'SUCCESS',
    ])
    expect(event.timeline.at(-1).detail).toContain('家属反馈')
    expect(event.observation_seconds).toBe(61)
    expect(event.risk_history).toEqual([])
  })

  it('API 无事件时不混入 Mock 风险、今日统计或趋势', () => {
    const preFallSummary = {
      risk_level: 'GREEN', instant_risk: 0.1, risk_30s: 0.08, trend_3min: 0.05,
      trend_direction: 'STABLE', personal_deviation: 0, environment_risk: 0,
      quality_penalty: 0, dominant_factors: ['normal_fluctuation'], evidence_ids: [],
      recommended_intervention: '仅记录为日常波动，不打扰老人。',
    }
    const dashboard = normalizeDashboard({
      residentId: 'resident-api', events: [], baseline: { pre_fall_summary: preFallSummary },
      device: { online: true, device_alias: 'camera-mock-001', adapter_mode: 'MOCK', source_mode: 'MOCK', simulated: true, collection_active: true },
    })
    expect(dashboard.current_risk).toBeNull()
    expect(dashboard.today.activity_minutes).toBeNull()
    expect(dashboard.risk_trend).toEqual([])
    expect(dashboard.pre_fall_summary).toEqual(preFallSummary)
    expect(dashboard.device.name).toBe('camera-mock-001')
    expect(dashboard.device.data_quality).toBeNull()
    expect(dashboard.device.collection_active).toBe(true)
  })

  it('规范化设备、空周报与基线状态', () => {
    expect(normalizeDevice({ online: true, device_alias: 'A', adapter_mode: 'EZVIZ_CLOUD', source_mode: 'LIVE_DEVICE', simulated: false, collection_active: true }))
      .toMatchObject({ name: 'A', adapter: 'EZVIZ_CLOUD', collection_active: true })
    expect(normalizeWeeklyReport({ trend: [], visitor_case: null, care: { event_id: 'event-mental-week', options: [] } }))
      .toMatchObject({ trend: [], visitor_case: null, care: { event_id: 'event-mental-week', options: [] } })
    const baseline = normalizeBaseline({ baselines: {
      rise_duration: { median: 3.5, mad: 0.4, sample_count: 12, distinct_days: 3, status: 'PROVISIONAL' },
      custom_metric: { median: 1, mad: 0.1, sample_count: 2, distinct_days: 1, status: 'INSUFFICIENT' },
    } })
    expect(baseline.metrics[0]).toMatchObject({ label: '起身时长', unit: '秒' })
    expect(baseline.metrics[1]).toMatchObject({ label: 'custom_metric', unit: '' })
    expect(baseline.baseline_progress).toEqual({ observed_days: 3, provisional_target_days: 3, stable_target_days: 7 })
  })
})
