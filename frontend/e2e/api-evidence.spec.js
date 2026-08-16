import { expect, test } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

const API_BASE = process.env.API_BASE_URL || 'http://127.0.0.1:8000'
const RESIDENT_ID = process.env.VITE_RESIDENT_ID || 'resident-frontend-api'

function stamp(round, seconds) {
  const baseSeconds = (7 + ((round - 1) * 10)) * 60 + seconds
  const minute = Math.floor(baseSeconds / 60)
  const second = baseSeconds % 60
  return `2026-07-31T03:${String(minute).padStart(2, '0')}:${String(second).padStart(2, '0')}+08:00`
}

function observation(round, kind, seconds, featureName, featureValue, unit) {
  return {
    schema_version: '1.0',
    observation_id: `obs-api-${round}-${kind}`,
    resident_id: RESIDENT_ID,
    timestamp: stamp(round, seconds),
    source: 'pose',
    feature_name: featureName,
    feature_value: featureValue,
    unit,
    location: 'living_room',
    confidence: 0.92,
    data_quality: 0.88,
    source_mode: 'MOCK',
    asset_id: `asset-api-${round}`,
    simulated: true,
    metadata: { acceptance_round: round },
  }
}

function evidence(round, kind, seconds, type, severity, currentValue, explanation, observationIds = null) {
  return {
    schema_version: '1.0',
    evidence_id: `evi-api-${round}-${kind}`,
    observation_ids: observationIds || (type === 'posture_recovered'
      ? [`obs-api-${round}-${kind}`, `obs-api-${round}-${kind}-angle`]
      : [`obs-api-${round}-${kind}`]),
    resident_id: RESIDENT_ID,
    timestamp: stamp(round, seconds),
    risk_domain: 'FALL',
    evidence_type: type,
    severity,
    confidence: 0.92,
    data_quality: 0.88,
    baseline_value: type === 'rapid_rise' ? 3.5 : (type === 'trunk_sway' ? 6.2 : (type === 'posture_recovered' ? 15 : null)),
    current_value: currentValue,
    baseline_deviation: type === 'rapid_rise' ? -2.3 : (type === 'trunk_sway' ? 2.8 : (type === 'posture_recovered' ? 0 : null)),
    time_scale: 'SHORT',
    location: 'living_room',
    explanation,
    adapter_version: 'frontend-api-acceptance-v1',
    source_mode: 'MOCK',
    simulated: true,
  }
}

function redactEvidence(value, key = '') {
  if (/token|secret|password|accesskey|authorization/i.test(key)) return '[REDACTED]'
  if (Array.isArray(value)) return value.map((item) => redactEvidence(item))
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => (
      [childKey, redactEvidence(childValue, childKey)]
    )))
  }
  if (typeof value === 'string' && /^https?:\/\//i.test(value)) return '[URL_REDACTED]'
  return value
}

function responseBody(text) {
  try { return JSON.parse(text) }
  catch { return text }
}

function apiPayload(body) {
  return body?.data ?? body
}

async function checkedPost(request, path, data, exchanges) {
  const response = await request.post(`${API_BASE}${path}`, { data })
  const text = await response.text()
  const body = responseBody(text)
  exchanges.push({
    sequence: exchanges.length + 1,
    request: { method: 'POST', path, body: data },
    response: { status: response.status(), body },
  })
  expect([200, 201], `${path}: ${text}`).toContain(response.status())
  return { status: response.status(), body }
}

async function checkedGet(request, path, exchanges) {
  const response = await request.get(`${API_BASE}${path}`)
  const text = await response.text()
  const body = responseBody(text)
  exchanges.push({
    sequence: exchanges.length + 1,
    request: { method: 'GET', path, body: null },
    response: { status: response.status(), body },
  })
  expect(response.status(), `${path}: ${text}`).toBe(200)
  return apiPayload(body)
}

function saveJson(directories, filename, value) {
  const serialized = `${JSON.stringify(redactEvidence(value), null, 2)}\n`
  directories.forEach((directory) => writeFileSync(resolve(directory, filename), serialized, 'utf8'))
}

async function saveScreenshot(page, artifactDir, deliverableDir, filename) {
  const screenshot = await page.screenshot({ path: resolve(artifactDir, filename), fullPage: true })
  writeFileSync(resolve(deliverableDir, filename), screenshot)
}

for (let round = 1; round <= 3; round += 1) {
  test(`FastAPI 前端闭环 ${round}/3`, async ({ page, request }) => {
    const artifactDir = resolve(process.cwd(), 'artifacts', 'api-evidence', `run-${round}`)
    const deliverableDir = resolve(process.cwd(), '..', 'deliverables', 'frontend-api-2026-07-31', `run-${round}`)
    const evidenceDirectories = [artifactDir, deliverableDir]
    const exchanges = []
    mkdirSync(artifactDir, { recursive: true })
    mkdirSync(deliverableDir, { recursive: true })
    await page.addInitScript(() => {
      if (!sessionStorage.getItem('yingmu-api-evidence-initialized')) {
        sessionStorage.removeItem('yingmu-audit-log')
        sessionStorage.setItem('yingmu-api-evidence-initialized', 'true')
      }
      sessionStorage.setItem('yingmu-data-mode', 'api')
    })
    const video = page.video()

    await checkedPost(request, '/api/v1/observations', observation(round, 'rapid-rise', 1, 'sit_to_stand_duration', 1.2, 'second'), exchanges)
    await checkedPost(request, '/api/v1/evidence', evidence(round, 'rapid-rise', 1, 'rapid_rise', 0.78, 1.2, '起身速度明显快于个人基线'), exchanges)
    await checkedPost(request, '/api/v1/observations', observation(round, 'trunk-sway', 5, 'trunk_sway_angle', 18, 'degree'), exchanges)
    const orange = await checkedPost(request, '/api/v1/evidence', evidence(round, 'trunk-sway', 5, 'trunk_sway', 0.82, 18, '快速起身后出现明显躯干摇晃'), exchanges)
    const eventId = orange.body.evaluation.event_id
    const interveningSnapshot = await checkedGet(request, `/api/v1/events/${eventId}`, exchanges)
    expect(interveningSnapshot.event_id).toBe(eventId)
    expect(interveningSnapshot.status).toBe('INTERVENING')

    await page.goto('/events')
    await expect(page.getByTestId('unified-timeline')).toContainText('起身速度明显快于个人基线')
    await page.goto(`/events/${eventId}`)
    await expect(page.getByText('正在干预').first()).toBeVisible()
    await expect(page.getByText('INTERVENING').first()).toBeVisible()
    await expect(page.getByText(eventId).first()).toBeVisible()
    await expect(page.getByTestId('event-sync-status')).toContainText('自动同步中')
    await saveScreenshot(page, artifactDir, deliverableDir, '01-intervening.png')

    const intervention = await checkedPost(request, `/api/v1/events/${eventId}/intervene`, {}, exchanges)
    expect(intervention.body.delivery_status).toBe('SUCCESS')
    await checkedPost(request, '/api/v1/observations', observation(round, 'posture-recovered', 29, 'stable_posture_duration', 15, 'second'), exchanges)
    await checkedPost(request, '/api/v1/observations', observation(round, 'posture-recovered-angle', 29, 'stable_trunk_angle_deg', 3.6, 'degree'), exchanges)
    await checkedPost(request, '/api/v1/evidence', evidence(
      round,
      'posture-recovered',
      29,
      'posture_recovered',
      0,
      15,
      '最大稳定躯干角度3.6度，连续稳定15秒，达到15秒恢复阈值',
      [`obs-api-${round}-posture-recovered`, `obs-api-${round}-posture-recovered-angle`],
    ), exchanges)
    const observingSnapshot = await checkedGet(request, `/api/v1/events/${eventId}`, exchanges)
    expect(observingSnapshot.event_id).toBe(eventId)
    expect(observingSnapshot.status).toBe('OBSERVING')

    await expect(page.getByText('观察期').first()).toBeVisible({ timeout: 8000 })
    await expect(page.getByText('OBSERVING').first()).toBeVisible({ timeout: 8000 })
    await expect(page.getByText(eventId).first()).toBeVisible()
    await saveScreenshot(page, artifactDir, deliverableDir, '02-observing.png')

    await checkedPost(request, '/api/v1/risk/evaluate', { resident_id: RESIDENT_ID, evaluated_at: stamp(round, 90) }, exchanges)
    const feedbackBody = {
      feedback_id: `feedback-api-${round}`,
      feedback_type: 'care',
      value: '已联系，近期一切正常',
      operator: 'family',
    }
    const firstFeedback = await checkedPost(request, `/api/v1/events/${eventId}/feedback`, feedbackBody, exchanges)
    const repeatedFeedback = await checkedPost(request, `/api/v1/events/${eventId}/feedback`, feedbackBody, exchanges)
    expect(firstFeedback.status).toBe(201)
    expect(repeatedFeedback.status).toBe(200)
    const resolvedSnapshot = await checkedGet(request, `/api/v1/events/${eventId}`, exchanges)
    expect(resolvedSnapshot.event_id).toBe(eventId)
    expect(resolvedSnapshot.status).toBe('RESOLVED')
    const eventSnapshots = [interveningSnapshot, observingSnapshot, resolvedSnapshot]
    expect(eventSnapshots.map((snapshot) => snapshot.event_id)).toEqual([eventId, eventId, eventId])

    await expect(page.getByText('已回落').first()).toBeVisible({ timeout: 8000 })
    await expect(page.getByText('RESOLVED').first()).toBeVisible({ timeout: 8000 })
    await expect(page.getByTestId('event-sync-status')).toContainText('同步已完成')
    await expect(page.getByText(eventId).first()).toBeVisible()
    await expect(page.getByText('ruleset-v1.0').first()).toBeVisible()
    await expect(page.getByText('已联系，近期一切正常').first()).toBeVisible()
    await expect(page.getByText(`后端暂无素材记录（asset-api-${round}）`).first()).toBeVisible()
    await page.getByRole('button', { name: '查看原始观测' }).first().click()
    await expect(page.getByTestId('evidence-trace')).toContainText(`obs-api-${round}-rapid-rise`)
    await saveScreenshot(page, artifactDir, deliverableDir, '03-resolved-trace.png')

    await page.goto('/')
    await expect(page.getByText('camera-mock-001').first()).toBeVisible()
    await expect(page.getByText('后端降级')).toHaveCount(0)
    await page.goto('/weekly')
    await expect(page.getByText('当前 API 未提供周报趋势序列')).toBeVisible()
    await expect(page.getByText('当前 API 未返回 visitor_case，不使用 Mock 访客数据填充')).toBeVisible()
    await page.goto('/baseline')
    await expect(page.getByText('当前 API 未提供活动时序数据，不使用 Mock 趋势补位')).toBeVisible()
    await expect(page.getByText('当前 API 暂无活动热力图时序数据')).toBeVisible()

    const logs = await page.evaluate(() => window.__YINGMU_AUDIT__?.export?.() || [])
    const serializedLogs = JSON.stringify(logs)
    expect(logs.some((entry) => entry.operation === 'event.detail' && entry.status === 'SUCCESS')).toBeTruthy()
    expect(logs.filter((entry) => entry.operation === 'asset.read' && entry.status === 'FAILED')).toHaveLength(1)
    expect(logs.some((entry) => entry.status === 'DEGRADED')).toBeFalsy()
    expect(serializedLogs).not.toMatch(/token=|password=|secret=|accesskey=/i)
    const currentEvidenceIds = new Set(resolvedSnapshot.evidence_ids || [])
    const ruleTraces = (resolvedSnapshot.rule_traces || []).filter((trace) => (
      trace.event_id === eventId || currentEvidenceIds.has(trace.evidence_id)
    ))
    expect(ruleTraces.filter((trace) => trace.next_status).map((trace) => trace.next_status)).toEqual([
      'INTERVENING', 'OBSERVING', 'RESOLVED',
    ])
    const stateTransitions = ruleTraces.map((trace) => ({
      trace_id: trace.trace_id,
      event_id: trace.event_id,
      evaluated_at: trace.evaluated_at,
      matched_rule: trace.matched_rule,
      previous_status: trace.previous_status,
      next_status: trace.next_status,
    }))
    const summary = {
      schema_version: '1.0',
      round,
      completed_at: new Date().toISOString(),
      result: 'PASS',
      data_mode: 'api',
      active_source: 'api',
      source_mode: 'MOCK',
      simulated: true,
      real_device_claimed: false,
      resident_id: RESIDENT_ID,
      event_id: eventId,
      event_id_consistent: true,
      automatic_refresh: true,
      page_reload_used: false,
      statuses: ['INTERVENING', 'OBSERVING', 'RESOLVED'],
      ruleset_version: 'ruleset-v1.0',
      feedback_statuses: [firstFeedback.status, repeatedFeedback.status],
      repository_screenshots: ['01-intervening.png', '02-observing.png', '03-resolved-trace.png'],
      local_video: `frontend/artifacts/api-evidence/run-${round}/screen-recording.webm`,
    }
    saveJson(evidenceDirectories, 'requests.json', exchanges.map((exchange) => ({ sequence: exchange.sequence, ...exchange.request })))
    saveJson(evidenceDirectories, 'responses.json', exchanges.map((exchange) => ({ sequence: exchange.sequence, ...exchange.response })))
    saveJson(evidenceDirectories, 'event-snapshots.json', eventSnapshots)
    saveJson(evidenceDirectories, 'rule-traces.json', ruleTraces)
    saveJson(evidenceDirectories, 'state-transitions.json', stateTransitions)
    saveJson(evidenceDirectories, 'intervention-result.json', resolvedSnapshot.interventions || [])
    saveJson(evidenceDirectories, 'audit-log.json', logs)
    saveJson(evidenceDirectories, 'summary.json', summary)

    await page.close()
    await video.saveAs(resolve(artifactDir, 'screen-recording.webm'))
  })
}
