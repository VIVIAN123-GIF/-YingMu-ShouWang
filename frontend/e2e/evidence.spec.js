import { expect, test } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

for (let round = 1; round <= 3; round += 1) {
  test(`固定闭环连续复现 ${round}/3`, async ({ page }) => {
    const runDir = resolve(process.cwd(), 'artifacts', 'evidence', `run-${round}`)
    mkdirSync(runDir, { recursive: true })
    await page.addInitScript(() => {
      if (!sessionStorage.getItem('yingmu-evidence-initialized')) {
        sessionStorage.removeItem('yingmu-audit-log')
        sessionStorage.setItem('yingmu-evidence-initialized', 'true')
      }
      sessionStorage.setItem('yingmu-data-mode', 'mock')
    })
    const video = page.video()
    const checkpoints = []

    await page.goto('/')
    await expect(page.getByRole('heading', { name: '今天的安全状态，一眼看清' })).toBeVisible()
    await expect(page.getByText('MOCK · 演示数据').first()).toBeVisible()
    checkpoints.push('首页安全水位与来源标识')
    await page.screenshot({ path: resolve(runDir, '01-home.png'), fullPage: true })

    await page.goto('/events')
    await expect(page.getByTestId('unified-timeline')).toBeVisible()
    await expect(page.locator('.unified-event')).toHaveCount(6)
    await expect(page.locator('[data-domain="FALL"]').first()).toBeVisible()
    await expect(page.locator('[data-domain="MENTAL"]').first()).toBeVisible()
    await expect(page.locator('[data-domain="FRAUD"]').first()).toBeVisible()
    await expect(page.locator('[data-domain="SYSTEM"]').first()).toBeVisible()
    checkpoints.push('四领域统一事件时间轴')
    await page.screenshot({ path: resolve(runDir, '02-timeline.png'), fullPage: true })

    await page.goto('/events/event-fall-intervening')
    const explanationPanel = page.getByTestId('agent-explanation-panel')
    await expect(explanationPanel).toContainText('智能体解释')
    await expect(explanationPanel).toContainText('老人快速起身后出现持续躯干摇摆')
    await expect(explanationPanel).toContainText('mock-agent-v1')
    await expect(page.getByTestId('agent-explanation-fallback-used')).toHaveText('false')
    await expect(page.getByTestId('agent-explanation-fallback')).toHaveCount(0)
    await expect(page.getByRole('button', { name: '发起干预' })).toBeVisible()
    const elderAction = page.getByTestId('elder-single-action')
    await expect(elderAction).toBeVisible()
    await expect(elderAction.getByRole('button')).toHaveCount(1)
    await expect(elderAction.getByRole('button', { name: '我已坐稳' })).toBeVisible()
    checkpoints.push('Mock智能体解释字段、独立干预动作与老人侧单一动作')
    await page.screenshot({ path: resolve(runDir, '03-single-action.png'), fullPage: true })

    await page.goto('/events/event-fall-100')
    await expect(page.getByTestId('event-action-timeline')).toContainText('INTERVENING')
    await expect(page.getByTestId('event-action-timeline')).toContainText('OBSERVING')
    await expect(page.getByTestId('event-action-timeline')).toContainText('RESOLVED')
    await expect(page.getByText('ruleset-v1.0')).toBeVisible()
    await expect(page.getByText('待素材核验 · 不伪装为实时视频')).toBeVisible()
    checkpoints.push('干预、观察、回落与诚实媒体降级')

    await page.getByRole('button', { name: '查看原始观测' }).first().click()
    await expect(page.getByTestId('evidence-trace')).toBeVisible()
    await expect(page.getByTestId('evidence-trace')).toContainText('obs-rapid-rise')
    await expect(page.getByTestId('evidence-trace')).toContainText('asset-fall-authorized')
    checkpoints.push('RiskEvent到Observation和素材追溯')
    await page.screenshot({ path: resolve(runDir, '04-event-trace.png') })
    await page.locator('.el-drawer').screenshot({ path: resolve(runDir, '05-provenance-drawer.png') })

    await page.goto('/events/event-tool-failed')
    await expect(page.getByText('暂无可追溯视频').first()).toBeVisible()
    checkpoints.push('Observation.asset_id=null显示暂无可追溯视频')

    const logs = await page.evaluate(() => window.__YINGMU_AUDIT__?.export?.() || [])
    expect(logs.some((entry) => entry.ruleset_version === 'ruleset-v1.0')).toBeTruthy()
    expect(JSON.stringify(logs)).not.toMatch(/token=|password=|secret=/i)
    writeFileSync(resolve(runDir, 'audit-log.json'), JSON.stringify(logs, null, 2), 'utf8')
    writeFileSync(resolve(runDir, 'summary.json'), JSON.stringify({
      round,
      completed_at: new Date().toISOString(),
      result: 'PASS',
      ruleset_version: 'ruleset-v1.0',
      source_mode: 'MOCK',
      media_verification: 'PENDING_ASSET',
      checkpoints,
    }, null, 2), 'utf8')

    await page.close()
    await video.saveAs(resolve(runDir, 'screen-recording.webm'))
  })
}
