import { expect, test } from '@playwright/test'

test('清除反馈记录在真实浏览器中有可见响应', async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem('yingmu-demo-authenticated', 'true')
    localStorage.setItem('yingmu-feedback-records-v1', JSON.stringify([{
      feedback_id: 'feedback-browser-check',
      event_id: 'event-mental-week',
      feedback_kind: 'CARE',
      value: '已联系，希望继续关注',
      operator: 'family',
      recorded_at: '2026-09-02T12:00:00+08:00',
      source_mode: 'RECORDED_REPLAY',
      simulated: true,
      saved_in_demo: true,
    }]))
  })
  await page.route('**/api/**', (route) => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'browser test offline fallback' }),
  }))
  await page.goto('/system')
  const feedbackAudit = page.getByTestId('feedback-audit')
  await expect(feedbackAudit).toContainText('已联系，希望继续关注')
  const recordCountBeforeClear = await feedbackAudit.locator('.recorded-feedback').count()

  await page.getByTestId('clear-feedback').click()
  await expect(page.getByRole('dialog', { name: '确认清除记录' })).toBeVisible()
  await page.getByTestId('clear-feedback-cancel').click()
  await expect(feedbackAudit.locator('.recorded-feedback')).toHaveCount(recordCountBeforeClear)
  await expect(feedbackAudit).toContainText('已联系，希望继续关注')

  await page.getByTestId('clear-feedback').click()
  await page.getByTestId('clear-feedback-confirm').click()

  await expect(feedbackAudit.locator('.recorded-feedback')).toHaveCount(0)
  await expect(feedbackAudit).toContainText('0 条')
  await expect(feedbackAudit).toContainText('尚未记录关怀反馈或身份核验')
  await expect(page.getByTestId('feedback-clear-notice')).toContainText('数据库审计记录未删除')
})

test('风险处置主路径中的按钮均产生可见页面响应', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('yingmu-demo-authenticated', 'true'))
  await page.route('**/api/**', (route) => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'browser test offline fallback' }),
  }))

  await page.goto('/events')
  await expect(page.getByRole('heading', { name: '风险事件与处置', exact: true })).toBeVisible()
  await expect(page.locator('[data-testid="unified-timeline"]')).toBeVisible()
  await expect(page.locator('[data-testid="risk-reviews"]')).toHaveCount(0)

  const disclosure = page.getByRole('button', { name: /工程复核与设备任务/ })
  await disclosure.click()
  await expect(disclosure).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('[data-testid="risk-reviews"]')).toBeVisible()
  await disclosure.click()
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  await expect(page.locator('[data-testid="risk-reviews"]')).toHaveCount(0)

  await page.locator('.timeline-event-card').first().click()
  await expect(page.getByRole('heading', { name: '风险事件详情', exact: true })).toBeVisible()
  const acknowledge = page.getByRole('button', { name: '我已看到，查看处理建议' })
  if (await acknowledge.isVisible()) await acknowledge.click()

  const comparisonDisclosure = page.getByRole('button', { name: /查看验证对照片段/ })
  if (await comparisonDisclosure.count()) {
    await comparisonDisclosure.click()
    await expect(comparisonDisclosure).toHaveAttribute('aria-expanded', 'true')
    const labels = await page.locator('.related-media-option strong').allTextContents()
    expect(new Set(labels).size).toBe(labels.length)
  }

  await page.getByRole('button', { name: '返回事件列表' }).click()
  await expect(page).toHaveURL(/\/events$/)
  await expect(page.getByRole('heading', { name: '风险事件与处置', exact: true })).toBeVisible()

  await page.goto('/replay')
  await expect(page.getByRole('heading', { name: '风险验证与回放', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '高低风险对照记录', exact: true })).toBeVisible()
  await page.getByRole('link', { name: '查看完整依据、风险事件与规则轨迹' }).click()
  await expect(page).toHaveURL(/\/events\//)
})
