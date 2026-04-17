import { defineConfig } from '@playwright/test';

// Heavy e2e config — real API + TTS + WhisperX. Paired with global-setup.ts
// that checks infra health.
//
// For sub-second pure-function tests see ``playwright.unit.config.ts``.
export default defineConfig({
  testDir: './e2e',
  timeout: 300000,        // 5 min per test (Fish API + WhisperX are slow)
  retries: 0,             // 不重试，失败就是失败
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],
  use: {
    baseURL: 'http://localhost:3010',
    screenshot: 'on',
    video: 'on',
    trace: 'on',
  },
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
