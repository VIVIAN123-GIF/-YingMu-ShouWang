import { describe, expect, it } from 'vitest'
import {
  deriveEventTitle, mergeDuplicateReplayOptions, normalizeBaseline, normalizeDashboard, normalizeDevice, normalizeEvent,
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
  it('同标题回放选项优先保留证据更完整且时间更新的事件', () => {
    const events = mergeDuplicateReplayOptions([
      { event_id: 'event-old', title: '风险事件', evidence_ids: ['evi-1'], updated_at: '2026-08-01T08:00:00+08:00', source_mode: 'RECORDED_REPLAY', simulated: true },
      { event_id: 'event-complete', title: '风险事件', evidence_ids: ['evi-1', 'evi-2'], updated_at: '2026-08-01T07:00:00+08:00', source_mode: 'RECORDED_REPLAY', simulated: true },
      { event_id: 'event-other', title: '正常事件', evidence_ids: [], updated_at: '2026-08-01T09:00:00+08:00', source_mode: 'RECORDED_REPLAY', simulated: true },
    ])

    expect(events.map((event) => event.event_id)).toEqual(['event-complete', 'event-other'])
  })

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

  it('数据库前缀的授权回放事件沿用简洁场景标题', () => {
    const normalEvent = {
      event_id: 'event-fi-resident-001-run-event-green-daily',
      source_mode: 'RECORDED_REPLAY',
      simulated: true,
      evidence_summary: [{ explanation: '旧的长说明文字' }],
    }
    const riskEvent = {
      event_id: 'event-fi-resident-001-run-event-fall-100',
      source_mode: 'RECORDED_REPLAY',
      simulated: true,
      evidence_summary: [{ explanation: '旧的长说明文字' }],
    }
    expect(deriveEventTitle(normalEvent)).toBe('正常动作对照')
    expect(deriveEventTitle(riskEvent)).toBe('受控风险动作')
    expect(normalizeEvent(normalEvent).demo_order).toBe(1)
    expect(normalizeEvent(riskEvent).demo_order).toBe(2)
  })

  it('接口未提供风险历史时使用规则轨迹中的真实评估分数', () => {
    const event = normalizeEvent({
      ...apiEvent,
      rule_traces: apiEvent.rule_traces.map((trace, index) => (
        index < 3
          ? { ...trace, score_components: { final_score: [0.82, 0.68, 0.31][index] } }
          : trace
      )),
    })

    expect(event.risk_history).toEqual([
      { time: '2026-07-31T03:07:28+08:00', score: 0.82 },
      { time: '2026-07-31T03:07:29+08:00', score: 0.68 },
      { time: '2026-07-31T03:08:30+08:00', score: 0.31 },
    ])
  })

  it('接口明确提供风险历史时优先保留接口数据', () => {
    const riskHistory = [{ time: '03:07:00', score: 0.74 }]
    const event = normalizeEvent({
      ...apiEvent,
      risk_history: riskHistory,
      rule_traces: apiEvent.rule_traces.map((trace) => ({ ...trace, score_components: { final_score: 0.82 } })),
    })

    expect(event.risk_history).toEqual(riskHistory)
  })

  it('把关怀反馈和身份核验记录追加到事件时间轴', () => {
    const event = normalizeEvent({
      ...apiEvent,
      feedback_records: [
        { feedback_id: 'feedback-care', event_id: 'event-api-001', feedback_kind: 'CARE', value: '已联系，希望继续关注', operator: 'family', recorded_at: '2026-07-31T03:09:00+08:00', saved_in_demo: true },
        { feedback_id: 'feedback-identity', event_id: 'event-api-001', feedback_kind: 'IDENTITY_VERIFICATION', value: '身份已确认，无需继续关注', operator: 'family', recorded_at: '2026-07-31T03:10:00+08:00', saved_in_demo: true },
      ],
    })
    expect(event.timeline.slice(-2).map((item) => item.title)).toEqual(['家属关怀反馈已记录', '身份信息核验已记录'])
    expect(event.timeline.at(-1).detail).toContain('身份已确认')
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
      device: { online: true, device_alias: 'camera-mock-001', adapter_mode: 'RECORDED_REPLAY', source_mode: 'RECORDED_REPLAY', simulated: true, collection_active: true },
    })
    expect(dashboard.current_risk).toBeNull()
    expect(dashboard.today.activity_minutes).toBeNull()
    expect(dashboard.risk_trend).toEqual([])
    expect(dashboard.pre_fall_summary).toEqual(preFallSummary)
    expect(dashboard.device.name).toBe('camera-mock-001')
    expect(dashboard.device.data_quality).toBeNull()
    expect(dashboard.device.collection_active).toBe(true)
  })

  it('融合历史中授权回放不会覆盖当前实时风险', () => {
    const replayEvent = {
      ...apiEvent, event_id: 'event-replay-newer', title: '较新的回放事件',
      risk_level: 'ORANGE', risk_score: 0.88, status: 'OPEN', updated_at: '2026-08-02T10:00:00+08:00',
      source_mode: 'RECORDED_REPLAY', simulated: true, rule_traces: [], interventions: [],
    }
    const liveEvent = {
      ...apiEvent, event_id: 'event-live-current', title: '当前实时事件',
      risk_level: 'YELLOW', risk_score: 0.42, status: 'OBSERVING', updated_at: '2026-08-01T10:00:00+08:00',
      source_mode: 'LIVE_DEVICE', simulated: false, rule_traces: [], interventions: [],
    }

    const dashboard = normalizeDashboard({ residentId: 'resident-api', events: [replayEvent, liveEvent] })

    expect(dashboard.current_risk).toMatchObject({ risk_level: 'YELLOW', risk_score: 0.42, status: 'OBSERVING' })
    expect(dashboard.recent_events).toHaveLength(2)
  })

  it('已解决事件使用最后一次规则评估作为首页当前状态，同时保留事件峰值', () => {
    const resolvedEvent = {
      ...apiEvent,
      risk_level: 'ORANGE',
      risk_score: 0.78,
      status: 'RESOLVED',
      updated_at: '2026-09-03T17:40:00+08:00',
      source_mode: 'RECORDED_REPLAY',
      simulated: true,
      rule_traces: [
        {
          event_id: 'event-api-001', evaluated_at: '2026-09-03T17:05:02+08:00',
          next_state: 'ORANGE', next_status: 'INTERVENING', score_components: { final_score: 0.78 },
        },
        {
          event_id: 'event-api-001', evaluated_at: '2026-09-03T17:06:30+08:00',
          next_state: 'GREEN', next_status: 'RESOLVED', score_components: { final_score: 0.18 },
        },
      ],
    }

    const dashboard = normalizeDashboard({ residentId: 'resident-api', events: [resolvedEvent] })

    expect(dashboard.current_risk).toMatchObject({
      risk_level: 'GREEN', risk_score: 0.18, status: 'RESOLVED',
      event_risk_level: 'ORANGE', event_risk_score: 0.78,
      summary: '风险水位已经回落，观察已完成。',
      recommended_action: '当前状态平稳，继续日常关注即可。',
      updated_at: '2026-09-03T17:06:30+08:00',
    })
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
    expect(baseline.metrics[1]).toMatchObject({ label: '其他趋势指标', unit: '' })
    expect(baseline.baseline_progress).toEqual({ observed_days: 3, provisional_target_days: 3, stable_target_days: 7 })
  })
})
