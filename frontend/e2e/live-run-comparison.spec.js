import { expect, test } from '@playwright/test'

const source = { source_mode: 'LIVE_DEVICE', simulated: false }

function horizon(score, attention) {
  return { window_seconds: 30, engineering_index: score, attention_level: attention }
}

function snapshot(id, phase, score, attention, eventId = null) {
  return {
    schema_version: 'forewarning-snapshot/1.0', snapshot_id: id, resident_id: 'resident-001',
    evaluated_at: phase === 'POST_INTERVENTION' ? '2026-09-02T10:02:00+08:00' : '2026-09-02T10:00:00+08:00',
    phase, assessment_status: 'VALID', confidence_level: 'HIGH', baseline_status: 'STABLE',
    components: { human_risk: score, personal_deviation: 0.08, environment_risk: 0, interaction_risk: 0 },
    instant: { ...horizon(score, attention), window_seconds: 10 },
    short_30s: horizon(Math.max(score - 0.02, 0), attention),
    trend_3min: { ...horizon(Math.max(score - 0.04, 0), attention), window_seconds: 180 },
    dominant_factors: phase === 'PRE_INTERVENTION'
      ? [{ factor: 'human_instability', contribution: 0.68, evidence_ids: ['evi-high-sway'] }]
      : [],
    degradation_reasons: [], evidence_ids: [], observation_ids: [],
    scene_config_id: 'living-room-c6c-20260831', event_id: eventId,
    intervention_result_id: phase === 'POST_INTERVENTION' ? 'result-high' : null,
    recommended_action: '保持观察', ruleset_version: 'ruleset-v1.5', ...source,
  }
}

function observation(id, featureName, value, unit, assetId, capturedAt) {
  return {
    schema_version: '1.0', observation_id: id, resident_id: 'resident-001', timestamp: capturedAt,
    source: 'gait_adapter', feature_name: featureName, feature_value: value, unit,
    location: 'living_room', confidence: 0.95, data_quality: 0.94, asset_id: assetId,
    metadata: { scene_config_id: 'living-room-c6c-20260831', camera_position_id: 'C6c-pos01' }, ...source,
  }
}

function evidence(id, observationId, type, value, capturedAt) {
  return {
    schema_version: '1.0', evidence_id: id, observation_ids: [observationId], resident_id: 'resident-001',
    timestamp: capturedAt, risk_domain: 'FALL', evidence_type: type, severity: 0.84,
    confidence: 0.95, data_quality: 0.94, baseline_value: 4, current_value: value,
    baseline_deviation: 2, time_scale: 'SHORT', location: 'living_room',
    explanation: type === 'rapid_rise' ? '起身速度明显偏快' : '起身后躯干持续摆动',
    adapter_version: 'gait-adapter-v1.5', ...source,
  }
}

function run(id, high) {
  const capturedAt = high ? '2026-09-02T10:00:00+08:00' : '2026-09-02T09:55:00+08:00'
  const assetId = high ? 'asset-high' : 'asset-low'
  const observations = [
    observation(`obs-${id}-rise`, 'sit_to_stand_duration', high ? 1.1 : 2.4, 's', assetId, capturedAt),
    observation(`obs-${id}-sway`, 'trunk_sway_angle', high ? 18.6 : 4.2, 'degree', assetId, capturedAt),
  ]
  const evidences = high ? [
    evidence('evi-high-rise', observations[0].observation_id, 'rapid_rise', 1.1, capturedAt),
    evidence('evi-high-sway', observations[1].observation_id, 'trunk_sway', 18.6, capturedAt),
  ] : []
  return {
    schema_version: 'field-run/1.0', run_id: id, resident_id: 'resident-001', captured_at: capturedAt,
    ...source, device_ref: 'device-7ab4c621f120', device_model: 'EZVIZ_C6C',
    camera_position_id: 'C6c-pos01', authorization_ref: 'authorization-9e0a912cf8c4',
    scene_config_id: 'living-room-c6c-20260831', task_status: high ? 'COMPLETED' : 'NO_EVIDENCE',
    task_result: { algorithm_summary: { modules: [{ module: 'GAIT', status: 'SUCCESS' }, { module: 'TRAJECTORY', status: 'NO_EVIDENCE' }] } },
    risk_level: high ? 'ORANGE' : 'GREEN', risk_score: high ? 0.84 : 0.12,
    current_risk_level: 'GREEN', current_risk_score: high ? 0.18 : 0.12, data_quality: 0.94,
    metrics: {
      rapid_rise: { detected: high, value: high ? 1.1 : 2.4, unit: 's', data_quality: 0.94, evidence_id: high ? 'evi-high-rise' : null, observation_id: observations[0].observation_id },
      trunk_sway: { detected: high, value: high ? 18.6 : 4.2, unit: 'degree', data_quality: 0.94, evidence_id: high ? 'evi-high-sway' : null, observation_id: observations[1].observation_id },
    },
    event: high ? { event_id: 'event-high', risk_level: 'GREEN', risk_score: 0, status: 'RESOLVED', recommended_action: '保持观察', ruleset_version: 'ruleset-v1.5' } : null,
    evidences, observations,
    rule_traces: high ? [{ trace_id: 'trace-high', event_id: 'event-high', evidence_id: 'evi-high-sway', evaluated_at: capturedAt, matched_rule: 'R-FALL-03', previous_state: 'GREEN', next_state: 'ORANGE' }] : [],
    interventions: high ? [{
      schema_version: '1.0', result_id: 'result-high', event_id: 'event-high', started_at: capturedAt,
      completed_at: '2026-09-02T10:02:00+08:00', action_type: 'voice', tool_name: 'ezviz_voice',
      delivery_status: 'SUCCESS', resident_response: 'stable', family_feedback: null, risk_after: 0.18,
      resolved: true, resolution_reason: '姿态恢复', operator: 'system', ...source,
    }] : [],
    forewarning_snapshots: high
      ? [snapshot('snapshot-high-pre', 'PRE_INTERVENTION', 0.84, 'ORANGE', 'event-high'), snapshot('snapshot-high-post', 'POST_INTERVENTION', 0.18, 'GREEN', 'event-high')]
      : [snapshot('snapshot-low', 'PERIODIC', 0.12, 'GREEN')],
  }
}

test('现场运行对照在桌面和移动视口均完整显示真实输出', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('yingmu-demo-authenticated', 'true'))
  await page.route('**/api/v1/residents/resident-001/field-runs*', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([run('run-high-live', true), run('run-low-live', false)]) })
  })
  await page.goto('http://127.0.0.1:5174/resident')
  const comparison = page.getByTestId('live-run-comparison')
  await expect(comparison).toContainText('run-high-live')
  await expect(comparison).toContainText('run-low-live')
  await expect(comparison).toContainText('Evidence 与 RuleTrace')
  await expect(comparison).toContainText('后续观察与风险回落')
  await expect(comparison).toContainText('-66%')
  await page.screenshot({ path: '../artifacts/ui-verification-20260902/live-run-comparison-desktop.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(comparison).toBeVisible()
  const box = await comparison.boundingBox()
  expect(box.x).toBeGreaterThanOrEqual(0)
  expect(box.x + box.width).toBeLessThanOrEqual(390)
  const table = comparison.getByRole('table')
  const tableWidths = await table.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }))
  expect(tableWidths.scrollWidth).toBeLessThanOrEqual(tableWidths.clientWidth + 1)
  await expect(table.getByRole('columnheader').nth(2)).toContainText('快速起身后摇晃')
  await page.screenshot({ path: '../artifacts/ui-verification-20260902/live-run-comparison-mobile.png', fullPage: true })
})
