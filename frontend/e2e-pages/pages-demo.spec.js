import { expect, test } from '@playwright/test'

const username = 'judge'
const password = 'YingMu2026Review!'
const routes = [
  ['#/', '首页安全水位'],
  ['#/resident', '老人档案与授权'],
  ['#/baseline', '个人基线与趋势'],
  ['#/events', '统一事件时间轴'],
  ['#/events/event-fall-100', '风险事件详情'],
  ['#/care', '家属关怀与身份核验'],
  ['#/weekly', '周报与核验'],
  ['#/system', '系统和设备状态'],
  ['#/replay', '场景回放'],
]

async function login(page) {
  await page.goto('./')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '进入演示' }).click()
  await expect(page.locator('.app-shell')).toBeVisible()
}

test('拒绝错误密码并接受评审账号', async ({ page }) => {
  await page.goto('./')
  await expect(page.getByRole('heading', { name: '萤目守望' })).toBeVisible()
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill('wrong-password')
  await page.getByRole('button', { name: '进入演示' }).click()
  await expect(page.getByRole('alert')).toHaveText('账号或密码不正确')
  await expect(page.locator('.app-shell')).toHaveCount(0)

  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '进入演示' }).click()
  await expect(page.locator('.app-shell')).toBeVisible()
})
test('Hash路由走查九个页面且不发出API请求', async ({ page }) => {
  const apiRequests = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.includes('/api/')) apiRequests.push(request.url())
  })
  await login(page)

  const banner = page.locator('.public-demo-banner')
  await expect(banner).toContainText('脱敏演示数据')
  await expect(banner).toContainText('MOCK / RECORDED_REPLAY')
  await expect(banner).toContainText('非实时设备')
  await expect(banner).toContainText('非老年人实测')

  for (const [hash, title] of routes) {
    await page.goto(hash)
    await expect(page).toHaveURL(new RegExp(`${hash.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`))
    await expect(page.locator('.navigation')).toContainText(title)
    await expect(banner).toBeVisible()
  }

  await page.goto('#/events/event-fall-100')
  await page.reload()
  await expect(page).toHaveURL(/#\/events\/event-fall-100$/)
  await expect(page.getByTestId('agent-explanation-panel')).toContainText('脱敏解释')
  expect(apiRequests).toEqual([])
  await page.screenshot({ path: 'artifacts/pages/desktop-event-detail.png', fullPage: true })
})

test('移动端布局无页面级横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page)
  await page.goto('#/events')
  await expect(page.locator('.public-demo-banner')).toBeVisible()
  await expect(page.getByTestId('unified-timeline')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  await page.screenshot({ path: 'artifacts/pages/mobile-events.png', fullPage: true })
})
