import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const REPLAY_EVENT_ID = 'event-fall-intervening'
const replayEvents = JSON.parse(readFileSync(resolve(process.cwd(), 'src/replay-data/events.json'), 'utf8'))
const contractObjects = JSON.parse(readFileSync(resolve(process.cwd(), 'contracts/v1/examples/four-objects.json'), 'utf8'))

function fallEvent(eventId) {
  const event = structuredClone(replayEvents.find((item) => item.event_id === REPLAY_EVENT_ID))
  event.event_id = eventId
  event.interventions.forEach((result) => { result.event_id = eventId })
  event.evidences = [structuredClone(contractObjects.evidence)]
  event.observations = [structuredClone(contractObjects.observation)]
  event.evidence_ids = [contractObjects.evidence.evidence_id]
  event.evidence_summary = [{
    evidence_id: contractObjects.evidence.evidence_id,
    evidence_type: contractObjects.evidence.evidence_type,
    explanation: contractObjects.evidence.explanation,
  }]
  event.forewarning_snapshots = []
  event.rule_traces = []
  return event
}

function stableResult(eventId) {
  return {
    schema_version: '1.0', result_id: `result-${eventId}-stable-browser`, event_id: eventId,
    started_at: '2026-09-02T12:00:00+08:00', completed_at: '2026-09-02T12:00:00+08:00',
    action_type: 'resident_response', tool_name: 'family_console', delivery_status: 'SUCCESS',
    resident_response: 'stable', family_feedback: null, risk_after: null, resolved: false,
    resolution_reason: null, operator: 'family', source_mode: 'RECORDED_REPLAY', simulated: true,
  }
}

async function openEvent(page, event) {
  await page.addInitScript(() => {
    sessionStorage.setItem('yingmu-demo-authenticated', 'true')
  })
  await page.route(`**/api/v1/events/${event.event_id}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(event),
  }))
  await page.route(`**/api/v1/events/${event.event_id}/forewarning`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }))
  await page.goto(`/events/${event.event_id}`)
  const acknowledgeRisk = page.getByRole('button', { name: '我已看到，查看处理建议' })
  await expect(acknowledgeRisk).toBeVisible()
  await acknowledgeRisk.click()
  await expect(acknowledgeRisk).toBeHidden()
}

test('已有坐稳确认在刷新后保持已记录状态', async ({ page }) => {
  const event = fallEvent('event-stable-browser-existing')
  event.interventions.push(stableResult(event.event_id))
  await openEvent(page, event)

  const stableButton = page.getByTestId('elder-stable-submit')
  await expect(stableButton).toHaveText('坐稳确认已记录')
  await expect(stableButton).toBeDisabled()
  await expect(page.getByText('确认后仍将继续观察事件状态。')).toBeVisible()
})

test('未确认事件点击我已坐稳后给出可见响应', async ({ page }) => {
  const event = fallEvent('event-stable-browser-new')
  await page.route(`**/api/v1/events/${event.event_id}/results`, async (route) => route.fulfill({
    status: 201,
    contentType: 'application/json',
    body: JSON.stringify(route.request().postDataJSON()),
  }))
  await openEvent(page, event)

  const stableButton = page.getByTestId('elder-stable-submit')
  await expect(stableButton).toHaveText('我已坐稳')
  await stableButton.click()

  await expect(stableButton).toHaveText('坐稳确认已记录')
  await expect(stableButton).toBeDisabled()
  await expect(page.getByText('确认后仍将继续观察事件状态。')).toBeVisible()
})

test('接口没有风险历史时展示规则轨迹中的真实评估分数', async ({ page }) => {
  const event = fallEvent('event-risk-history-from-traces')
  event.risk_history = []
  event.rule_traces = [
    {
      event_id: event.event_id, evidence_id: event.evidence_ids[0], evaluated_at: '2026-09-02T04:42:29+08:00',
      matched_rule: 'R-FALL-03', previous_state: 'GREEN', next_state: 'ORANGE', next_status: 'INTERVENING',
      score_components: { final_score: 0.82 },
    },
    {
      event_id: event.event_id, evidence_id: event.evidence_ids[0], evaluated_at: '2026-09-02T04:46:29+08:00',
      matched_rule: 'R-FALL-04', previous_state: 'ORANGE', next_state: 'ORANGE', previous_status: 'INTERVENING',
      next_status: 'INTERVENING', score_components: { final_score: 0.82 },
    },
  ]
  await openEvent(page, event)

  await expect(page.getByText('风险趋势 · 规则评估记录')).toBeVisible()
  await expect(page.getByText('2 个评估点')).toBeVisible()
  await expect(page.getByText('暂无逐点风险分，请查看上方规则与动作时间轴。')).toHaveCount(0)
  const chart = page.getByLabel('风险事件规则评估分数趋势图')
  await expect(chart.locator('svg')).toBeVisible()
  await expect(chart).toContainText('04:42:29')
  await expect(chart).toContainText('04:46:29')
})
