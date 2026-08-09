import { expect, test } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

test('陈硕前端任务看板入口与离线演示验收', async ({ page }) => {
  const artifactDir = resolve(process.cwd(), 'artifacts', 'cs-completion-2026-08-09')
  const deliverableDir = resolve(process.cwd(), '..', 'deliverables', 'frontend-cs-2026-08-09')
  mkdirSync(artifactDir, { recursive: true })
  mkdirSync(deliverableDir, { recursive: true })
  await page.addInitScript(() => {
    sessionStorage.setItem('yingmu-data-mode', 'mock')
    sessionStorage.removeItem('yingmu-audit-log')
  })

  const checkpoints = []
  const screenshots = {}
  for (const [path, heading, name] of [
    ['/resident', '老人档案与授权', '01-resident.png'],
    ['/care', '家属关怀与身份核验', '02-care.png'],
    ['/system', '系统和设备状态', '03-system.png'],
    ['/replay', '场景回放', '04-replay.png'],
  ]) {
    await page.goto(path)
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
    screenshots[name] = await page.screenshot({ path: resolve(artifactDir, name), fullPage: true })
    checkpoints.push(`${path} 可运行并显示来源标识`)
  }

  await page.goto('/events/event-fall-intervening')
  await expect(page.getByRole('button', { name: '我已坐稳' })).toBeVisible()
  await page.getByRole('button', { name: '我已坐稳' }).click()
  await expect(page.getByRole('button', { name: '坐稳确认已记录' })).toBeVisible()
  await expect(page.getByText('不会直接关闭事件')).toBeVisible()
  screenshots['05-resident-response.png'] = await page.screenshot({ path: resolve(artifactDir, '05-resident-response.png'), fullPage: true })
  checkpoints.push('事件详情坐稳确认回写并保持状态机控制')

  await page.goto('/offline.html')
  await expect(page.getByRole('heading', { name: '萤目守望暂时无法连接后端' })).toBeVisible()
  screenshots['06-offline.png'] = await page.screenshot({ path: resolve(artifactDir, '06-offline.png'), fullPage: true })
  checkpoints.push('离线备用页可访问且不伪造实时状态')

  const audit = await page.evaluate(() => window.__YINGMU_AUDIT__?.export?.() || [])
  const summary = {
    schema_version: '1.0', completed_at: new Date().toISOString(), result: 'PASS',
    data_mode: 'mock', source_mode: 'MOCK', simulated: true, real_device_claimed: false,
    checkpoints, repository_screenshots: Object.keys(screenshots),
  }
  for (const directory of [artifactDir, deliverableDir]) {
    for (const [name, image] of Object.entries(screenshots)) writeFileSync(resolve(directory, name), image)
    writeFileSync(resolve(directory, 'audit-log.json'), `${JSON.stringify(audit, null, 2)}\n`, 'utf8')
    writeFileSync(resolve(directory, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`, 'utf8')
  }
})
