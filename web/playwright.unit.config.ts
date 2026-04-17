import { defineConfig } from '@playwright/test';

// Sub-second pure-function tests (e.g. karaoke time→char mapping).
// No browser, no server, no globalSetup — run with:
//
//     cd web && npx playwright test -c playwright.unit.config.ts
//
// Kept separate from playwright.config.ts because the e2e config's
// globalSetup demands live API + Next.js servers; unit tests must run
// without any infra (CI, pre-commit, local).
export default defineConfig({
  testDir: './tests',
  timeout: 10_000,
  retries: 0,
  reporter: [['list']],
  projects: [{ name: 'unit', use: {} }],
});
