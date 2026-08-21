import { expect, test } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

test('8月13日前端周报、关怀与诈骗核验验收', async ({ page }) => {
  const artifactDir = resolve(process.cwd(), 'artifacts', 'weekly-evidence-2026-08-13')
  const deliverableDir = resolve(process.cwd(), '..', 'deliverables', 'frontend-2026-08-13')
  mkdirSync(artifactDir, { recursive: true })
  mkdirSync(deliverableDir, { recursive: true })

  await page.addInitScript(() => {
    sessionStorage.removeItem('yingmu-audit-log')
    sessionStorage.setItem('yingmu-data-mode', 'mock')
  })
  await page.goto('/weekly')

  await expect(page.getByRole('heading', { name: '本周值得关注的变化' })).toBeVisible()
  await expect(page.getByText('本周最多主动汇总一次')).toBeVisible()
  await expect(page.getByText('未授权访客 A')).toBeVisible()
  await expect(page.getByText('高风险组合词')).toBeVisible()
  const screenshots = {
    '01-weekly-initial.png': await page.screenshot({ path: resolve(artifactDir, '01-weekly-initial.png'), fullPage: true }),
  }

  const careRadio = page.getByRole('radio', { name: '已联系，希望继续关注' })
  await careRadio.evaluate((input) => {
    input.click()
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await expect(careRadio).toBeChecked()
  await page.getByRole('button', { name: '记录关怀反馈' }).click()
  await expect(page.getByRole('button', { name: '关怀反馈已记录' })).toBeVisible()
  screenshots['02-care-submitted.png'] = await page.screenshot({ path: resolve(artifactDir, '02-care-submitted.png'), fullPage: true })

  const verifyRadio = page.getByRole('radio', { name: '存在财产风险，转人工处理' })
  await verifyRadio.evaluate((input) => {
    input.click()
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await expect(verifyRadio).toBeChecked()
  await page.getByRole('button', { name: '提交身份核验' }).click()
  await expect(page.getByRole('button', { name: '身份核验已记录' })).toBeVisible()
  screenshots['03-verify-submitted.png'] = await page.screenshot({ path: resolve(artifactDir, '03-verify-submitted.png'), fullPage: true })

  const audit = await page.evaluate(() => window.__YINGMU_AUDIT__?.export?.() || [])
  const feedbackEvents = audit.filter((entry) => entry.operation === 'feedback.write' && entry.status === 'MOCK')
  expect(feedbackEvents).toHaveLength(2)
  expect(JSON.stringify(audit)).not.toMatch(/token=|password=|secret=|accesskey=/i)

  const summary = {
    schema_version: '1.0',
    completed_at: new Date().toISOString(),
    result: 'PASS',
    data_mode: 'mock',
    source_mode: 'RECORDED_REPLAY',
    simulated: true,
    real_device_claimed: false,
    checkpoints: [
      '黄色周报与低打扰原则',
      '家属关怀反馈提交',
      '诈骗访客三类证据与身份核验提交',
    ],
    repository_screenshots: [
      '01-weekly-initial.png',
      '02-care-submitted.png',
      '03-verify-submitted.png',
    ],
  }
  for (const directory of [artifactDir, deliverableDir]) {
    for (const [name, image] of Object.entries(screenshots)) writeFileSync(resolve(directory, name), image)
    writeFileSync(resolve(directory, 'audit-log.json'), `${JSON.stringify(audit, null, 2)}\n`, 'utf8')
    writeFileSync(resolve(directory, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`, 'utf8')
  }
})
