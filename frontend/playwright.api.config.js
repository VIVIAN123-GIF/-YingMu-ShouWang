import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'api-evidence.spec.js',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  outputDir: 'artifacts/api-evidence/playwright-raw',
  reporter: [
    ['list'],
    ['html', { outputFolder: 'artifacts/api-evidence/report', open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    channel: 'msedge',
    headless: true,
    viewport: { width: 1600, height: 1000 },
    video: 'on',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5173',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
