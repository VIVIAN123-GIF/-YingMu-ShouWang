import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from '@playwright/test'

const baseUrl = process.env.YINGMU_DEMO_URL || 'http://127.0.0.1:5190'
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

async function expectText(text) {
  await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible' })
}

async function expectPlayableVideo(label) {
  await page.locator('video').first().waitFor({ state: 'visible' })
  await page.waitForFunction(() => {
    const video = document.querySelector('video')
    return Boolean(video && video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0)
  })
  const media = await page.locator('video').first().evaluate((video) => ({
    src: video.currentSrc || video.src,
    readyState: video.readyState,
    width: video.videoWidth,
    height: video.videoHeight,
    duration: video.duration,
  }))
  if (!media.src.includes(label)) throw new Error(`Expected video ${label}, got ${media.src}`)
  return media
}

try {
  await page.goto(`${baseUrl}/replay`, { waitUntil: 'networkidle' })
  await expectText('正常动作对照')
  const normal = await expectPlayableVideo('new-normal-control-take02.mp4')
  await page.screenshot({ path: resolve(outputDir, '01-normal-replay.png'), fullPage: true })

  await page.locator('.replay-selector .el-select').click()
  await page.getByText('2. 受控风险动作', { exact: true }).click()
  await expectText('横向漂移0.38为录屏走查模拟注入值')
  const risk = await expectPlayableVideo('new-risk-left-take03.mp4')
  await page.screenshot({ path: resolve(outputDir, '02-risk-replay.png'), fullPage: true })

  await page.getByRole('link', { name: '查看完整依据、风险事件与规则轨迹' }).click()
  await page.waitForURL(/\/events\/event-fall-100$/)
  const acknowledge = page.getByRole('button', { name: '我已看到，查看处理建议' })
  const dialogVisible = await acknowledge.waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false)
  if (dialogVisible) await acknowledge.click()
  await expectText('干预前后观察对比')
  await expectText('工程指数回落')
  await expectPlayableVideo('new-risk-left-take03.mp4')
  const explanationPanel = page.getByTestId('agent-explanation-panel')
  await explanationPanel.getByText('授权回放解释', { exact: true }).waitFor()
  const explanationText = await explanationPanel.innerText()
  if (explanationText.includes('模板降级解释') || explanationText.includes('是否使用降级解释') || explanationText.includes('萤石服务端语音尚未验证')) {
    throw new Error(`Unexpected fallback wording in replay explanation: ${explanationText}`)
  }
  await explanationPanel.screenshot({ path: resolve(outputDir, '03-agent-replay-explanation.png') })

  await page.getByRole('button', { name: /规则判断与质量门槛/ }).click()
  await expectText('R-FALL-03-DEMO')
  await page.screenshot({ path: resolve(outputDir, '03-event-detail-rules.png'), fullPage: true })

  await page.getByRole('button', { name: /查看验证对照片段/ }).click()
  const relatedMedia = page.locator('[data-testid="related-media-selector"] .related-media-option')
  if (await relatedMedia.count() !== 2) throw new Error(`Expected 2 new related clips, got ${await relatedMedia.count()}`)
  await page.getByTestId('related-media-new-recovery-take01').click()
  const recovery = await expectPlayableVideo('new-recovery-take01.mp4')
  await page.screenshot({ path: resolve(outputDir, '04-recovery-media.png'), fullPage: true })

  if (errors.length) throw new Error(errors.join('\n'))
  console.log(JSON.stringify({ baseUrl, normal, risk, recovery, errors }, null, 2))
} finally {
  await browser.close()
}
