import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from '@playwright/test'

const baseUrl = process.env.YINGMU_DEMO_URL || 'http://127.0.0.1:5191'
const eventId = process.env.YINGMU_DEMO_EVENT_ID || 'event-fi-resident-001-f066ca33-event-fall-100'
const outputDir = resolve(import.meta.dirname, '../../artifacts/new-video-review-20260903/browser-verification')
await mkdir(outputDir, { recursive: true })

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
const errors = []
page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`console: ${message.text()}`)
})
page.on('requestfailed', (request) => errors.push(`requestfailed: ${request.url()} ${request.failure()?.errorText || ''}`))

try {
  const eventResponse = await page.request.get(`${baseUrl}/api/v1/events/${eventId}`)
  if (!eventResponse.ok()) throw new Error(`Event API failed: ${eventResponse.status()}`)
  const eventPayload = await eventResponse.json()
  const eventData = eventPayload?.data || eventPayload
  const traceScores = (eventData.rule_traces || []).map((trace) => trace?.score_components?.final_score)
  if (JSON.stringify(traceScores) !== JSON.stringify([0.78, 0.36, 0.18])) {
    throw new Error(`Unexpected risk history scores: ${JSON.stringify(traceScores)}`)
  }

  await page.goto(`${baseUrl}/replay`, { waitUntil: 'domcontentloaded' })
  await page.locator('.replay-selector .el-select').waitFor({ state: 'visible' })
  await page.locator('.replay-selector .el-select').click()
  await page.getByRole('option', { name: '1. 正常动作对照', exact: true }).waitFor()
  await page.getByRole('option', { name: '2. 受控风险动作', exact: true }).waitFor()
  const removedWording = page.getByText(/新拍|演示数据|演示闭环/)
  if (await removedWording.count()) {
    throw new Error(`Replay selector still contains the removed title wording: ${JSON.stringify(await removedWording.allTextContents())}`)
  }
  await page.keyboard.press('Escape')

  await page.goto(`${baseUrl}/events/${eventId}`, { waitUntil: 'networkidle' })
  const acknowledge = page.getByRole('button', { name: '我已看到，查看处理建议' })
  const dialogVisible = await acknowledge.waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false)
  if (dialogVisible) await acknowledge.click()

  await page.getByTestId('risk-engine-panel').getByText('78', { exact: true }).first().waitFor()
  await page.getByText('干预前后观察对比', { exact: true }).waitFor()
  await page.getByText('工程指数回落', { exact: true }).waitFor()
  await page.getByText('3 个评估点', { exact: true }).waitFor()
  const explanationPanel = page.getByTestId('agent-explanation-panel')
  await explanationPanel.getByText('授权回放解释', { exact: true }).waitFor()
  const explanationText = await explanationPanel.innerText()
  if (explanationText.includes('模板降级解释') || explanationText.includes('是否使用降级解释') || explanationText.includes('萤石服务端语音尚未验证')) {
    throw new Error(`Unexpected fallback wording in API replay explanation: ${explanationText}`)
  }
  await page.locator('video').first().waitFor({ state: 'visible' })
  await page.waitForFunction(() => {
    const video = document.querySelector('video')
    return Boolean(video && video.readyState >= 2 && video.videoWidth > 0)
  })
  const riskSource = await page.locator('video').first().evaluate((video) => video.currentSrc || video.src)
  if (!riskSource.includes('new-risk-left-take03.mp4')) throw new Error(`Unexpected risk video: ${riskSource}`)

  await page.getByRole('button', { name: /规则判断与质量门槛/ }).click()
  await page.getByText('R-FALL-03-DEMO', { exact: false }).first().waitFor()
  await page.getByRole('button', { name: /查看验证对照片段/ }).click()
  await page.getByTestId('related-media-new-recovery-take01').click()
  await page.waitForFunction(() => document.querySelector('video')?.currentSrc.includes('new-recovery-take01.mp4'))
  const riskHistoryPanel = page.getByText('风险水位已经回落', { exact: true }).locator('xpath=ancestor::article[1]')
  await riskHistoryPanel.screenshot({ path: resolve(outputDir, '06-risk-history.png') })
  await page.screenshot({ path: resolve(outputDir, '05-api-database-event.png'), fullPage: true })

  if (errors.length) throw new Error(errors.join('\n'))
  console.log(JSON.stringify({ baseUrl, eventId, riskSource, finalVideo: await page.locator('video').first().evaluate((video) => video.currentSrc), errors }, null, 2))
} finally {
  await browser.close()
}
