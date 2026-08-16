import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  globalSetup: './e2e/global-setup.ts',
  use: { baseURL: 'http://127.0.0.1:52888', viewport: { width: 1440, height: 960 } },
})
