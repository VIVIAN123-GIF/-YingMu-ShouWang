import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LiveRunComparisonCard from '../components/risk/LiveRunComparisonCard.vue'

function snapshot(id, phase, score, eventId = null) {
  return {
    snapshot_id: id, phase, evaluated_at: `2026-09-02T10:${phase === 'POST_INTERVENTION' ? '02' : '00'}:00+08:00`,
    instant: { engineering_index: score }, short_30s: { engineering_index: score - 0.02 }, trend_3min: { engineering_index: score - 0.04 },
    dominant_factors: phase === 'PRE_INTERVENTION' ? [{ factor: 'human_instability', contribution: 0.68 }] : [],
    event_id: eventId,
  }
}

function run(id, riskLevel, capturedAt, overrides = {}) {
  return {
    run_id: id, resident_id: 'resident-001', captured_at: capturedAt,
    source_mode: 'LIVE_DEVICE', simulated: false, device_ref: 'device-live', device_model: 'EZVIZ_C6C',
    camera_position_id: 'C6c-pos01', authorization_ref: 'authorization-live',
    task_status: riskLevel === 'GREEN' ? 'NO_EVIDENCE' : 'COMPLETED',
    task_result: { algorithm_summary: { modules: [{ module: 'GAIT', status: 'SUCCESS' }] } },
    risk_level: riskLevel, risk_score: riskLevel === 'GREEN' ? 0.12 : 0.84,
    current_risk_level: riskLevel === 'GREEN' ? 'GREEN' : 'GREEN', current_risk_score: riskLevel === 'GREEN' ? 0.12 : 0.18,
    data_quality: 0.94,
    metrics: {
      rapid_rise: { detected: riskLevel !== 'GREEN', value: riskLevel === 'GREEN' ? 2.4 : 1.1, unit: 's' },
      trunk_sway: { detected: riskLevel !== 'GREEN', value: riskLevel === 'GREEN' ? 4.2 : 18.6, unit: 'degree' },
    },
    event: riskLevel === 'GREEN' ? null : { event_id: `event-${id}`, status: 'RESOLVED' },
    evidences: riskLevel === 'GREEN' ? [] : [{ evidence_id: `evi-${id}`, evidence_type: 'trunk_sway', explanation: '起身后持续摇晃', data_quality: 0.94 }],
    rule_traces: riskLevel === 'GREEN' ? [] : [{ trace_id: `trace-${id}`, matched_rule: 'R-FALL-03', previous_state: 'GREEN', next_state: 'ORANGE' }],
    interventions: riskLevel === 'GREEN' ? [] : [{ action_type: 'voice', delivery_status: 'SUCCESS', resolved: true, risk_after: 0.18 }],
    forewarning_snapshots: riskLevel === 'GREEN' ? [snapshot(`snap-${id}`, 'PERIODIC', 0.12)] : [snapshot(`snap-${id}-pre`, 'PRE_INTERVENTION', 0.84, `event-${id}`), snapshot(`snap-${id}-post`, 'POST_INTERVENTION', 0.18, `event-${id}`)],
    ...overrides,
  }
}

describe('现场高低风险运行对照', () => {
  it('只配对同一真实设备、机位、居民与授权，并显示恢复快照', () => {
    const wrapper = mount(LiveRunComparisonCard, {
      props: { runs: [
        run('run-low', 'GREEN', '2026-09-02T09:55:00+08:00'),
        run('run-high', 'ORANGE', '2026-09-02T10:00:00+08:00'),
        run('run-other-camera', 'GREEN', '2026-09-02T09:58:00+08:00', { camera_position_id: 'C6c-pos02' }),
        run('run-replay', 'ORANGE', '2026-09-02T10:05:00+08:00', { source_mode: 'RECORDED_REPLAY', simulated: true }),
      ] },
      global: { stubs: {
        SourceBadge: { template: '<span>LIVE_DEVICE · 真实</span>' },
        RiskBadge: { props: ['level'], template: '<span class="risk-stub">{{ level }}</span>' },
        'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
        'el-empty': { props: ['description'], template: '<div>{{ description }}</div>' },
        'el-select': { template: '<div><slot /></div>' },
        'el-option': { props: ['label', 'value'], template: '<span class="run-option" :data-value="value">{{ label }}</span>' },
      } },
    })

    expect(wrapper.text()).toContain('run-low')
    expect(wrapper.text()).toContain('run-high')
    expect(wrapper.text()).not.toContain('run-other-camera')
    expect(wrapper.text()).not.toContain('run-replay')
    expect(wrapper.get('[data-testid="live-run-evidence"]').text()).toContain('evi-run-high')
    expect(wrapper.get('[data-testid="live-run-evidence"]').text()).toContain('trace-run-high')
    expect(wrapper.get('[data-testid="live-run-recovery"]').text()).toContain('干预后')
    expect(wrapper.get('[data-testid="live-run-recovery"]').text()).toContain('-66%')
  })

  it('轮询刷新后保留仍然有效的手动运行选择', async () => {
    const low = run('run-low', 'GREEN', '2026-09-02T09:55:00+08:00')
    const olderHigh = run('run-high-older', 'ORANGE', '2026-09-02T10:00:00+08:00')
    const latestHigh = run('run-high-latest', 'ORANGE', '2026-09-02T10:05:00+08:00')
    const wrapper = mount(LiveRunComparisonCard, {
      props: { runs: [low, olderHigh, latestHigh] },
      global: { stubs: {
        SourceBadge: { template: '<span>LIVE_DEVICE · 真实</span>' },
        RiskBadge: { props: ['level'], template: '<span>{{ level }}</span>' },
        'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
        'el-empty': { props: ['description'], template: '<div>{{ description }}</div>' },
        'el-select': {
          props: ['modelValue'], emits: ['update:modelValue'],
          template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
        },
        'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
      } },
    })

    const highSelect = wrapper.get('[data-testid="high-run-select"]')
    expect(highSelect.element.value).toBe('run-high-latest')
    await highSelect.setValue('run-high-older')
    await wrapper.setProps({ runs: [{ ...latestHigh }, { ...olderHigh }, { ...low }] })
    expect(highSelect.element.value).toBe('run-high-older')
  })
})
