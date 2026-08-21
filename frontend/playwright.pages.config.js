import { defineConfig } from '@playwright/test'

const publicPagesUrl = process.env.PAGES_BASE_URL

export default defineConfig({
  testDir: './e2e-pages',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: publicPagesUrl ? 2 : 0,
  outputDir: 'artifacts/pages/playwright-raw',
  reporter: [['list'], ['html', { outputFolder: 'artifacts/pages/report', open: 'never' }]],
  use: {
    baseURL: publicPagesUrl || 'http://127.0.0.1:4173/-YingMu-ShouWang/',
    headless: true,
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: publicPagesUrl ? undefined : {
    command: 'npm run preview:pages -- --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173/-YingMu-ShouWang/',
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
