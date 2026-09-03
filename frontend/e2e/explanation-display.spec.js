import { expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const EVENT_ID = 'event-fall-intervening'
const OUTPUT_DIR = resolve(process.cwd(), 'artifacts', 'explanation-review')

function explanation(status) {
  if (status === 'PENDING') return {
    event_id: EVENT_ID, status, request_id: 'review-pending', event_version_hash: null,
    generated_by: null, fallback_used: null, attempt_count: 0, error_code: null,
    created_at: '2026-08-16T01:30:40Z', completed_at: null, explanation: null,
  }
  const fallback = status === 'FALLBACK'
  const generatedBy = fallback ? 'template-fallback-v1' : 'qwen3.6-flash'
  return {
    event_id: EVENT_ID,
    status,
    request_id: `review-${status.toLowerCase()}`,
    event_version_hash: 'review-version-1',
    generated_by: generatedBy,
    fallback_used: fallback,
    attempt_count: 1,
    error_code: null,
    created_at: '2026-08-16T01:30:40Z',
    completed_at: '2026-08-16T01:30:45Z',
    explanation: {
      schema_version: 'agent-explanation/1.0',
      request_id: `review-${status.toLowerCase()}`,
      event_id: EVENT_ID,
      summary: fallback ? '智能体暂不可用，当前展示规则模板解释。' : '老人快速起身后出现持续躯干摇摆，建议先坐稳观察。',
      reasoning_points: ['快速起身与躯干摇摆 Evidence 同时出现。'],
      recommended_action_text: '先坐稳，扶住身边固定物。',
      capability_notice: '萤石服务端语音尚未验证，当前使用Mock语音或文字提醒。',
      generated_by: generatedBy,
      fallback_used: fallback,
    },
  }
}

for (const status of ['SUCCESS', 'FALLBACK']) {
  test(`智能体解释 ${status} 展示截图`, async ({ page }) => {
    mkdirSync(OUTPUT_DIR, { recursive: true })
    await page.addInitScript(() => sessionStorage.setItem('yingmu-data-mode', 'mock'))
    let explanationReads = 0
    await page.route('**/api/v1/events/*/explanation', async (route) => {
      explanationReads += 1
      const responseStatus = status === 'SUCCESS' && explanationReads === 1 ? 'PENDING' : status
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(explanation(responseStatus)) })
    })

    const video = page.video()
    await page.goto(`/events/${EVENT_ID}`)
    const panel = page.getByTestId('agent-explanation-panel')
    if (status === 'SUCCESS') {
      await expect(panel.getByTestId('agent-explanation-pending')).toContainText('解释生成中')
      await expect(page.getByTestId('risk-engine-panel')).toBeVisible()
      await expect(page.getByTestId('evidence-panel')).toBeVisible()
      await expect(page.getByTestId('evidence-panel')).toContainText('当前值')
      await expect(page.getByTestId('evidence-panel')).toContainText('个人基线')
      await page.screenshot({ path: resolve(OUTPUT_DIR, 'pending.png'), fullPage: true })
    }
    await expect(panel.getByTestId('agent-explanation-generated-by')).toHaveText(
      status === 'SUCCESS' ? '智能解释模型' : '系统备用解释模板',
    )
    await expect(panel.getByTestId('agent-explanation-fallback-used')).toHaveText(status === 'SUCCESS' ? 'false' : 'true')
    await expect(panel.getByTestId('agent-explanation-created-at')).toHaveText('2026/08/16 09:30:40')
    await expect(panel.getByTestId('agent-explanation-completed-at')).toHaveText('2026/08/16 09:30:45')
    await expect(panel).toContainText('萤石服务端语音尚未验证，当前使用Mock语音或文字提醒。')
    await expect(page.getByText('MOCK · 演示数据').first()).toBeVisible()
    await panel.screenshot({ path: resolve(OUTPUT_DIR, `${status.toLowerCase()}.png`) })
    if (status === 'SUCCESS') {
      await expect(page.getByTestId('intervention-result-panel')).toBeVisible()
      await page.screenshot({ path: resolve(OUTPUT_DIR, 'four-regions.png'), fullPage: true })
      await page.close()
      await video.saveAs(resolve(OUTPUT_DIR, 'controlled-closure.webm'))
    }
  })
}

test('RECORDED_REPLAY 来源标签截图', async ({ page }) => {
  mkdirSync(OUTPUT_DIR, { recursive: true })
  await page.addInitScript(() => sessionStorage.setItem('yingmu-data-mode', 'mock'))
  await page.route('**/api/v1/events/*/explanation', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      ...explanation('PENDING'), event_id: 'event-mental-week',
    }) })
  })
  await page.goto('/events/event-mental-week')
  const source = page.getByText('RECORDED_REPLAY · 授权回放').first()
  await expect(source).toBeVisible()
  await expect(page.getByText('模拟实验回放').first()).toBeVisible()
  await source.screenshot({ path: resolve(OUTPUT_DIR, 'recorded-replay.png') })
})
