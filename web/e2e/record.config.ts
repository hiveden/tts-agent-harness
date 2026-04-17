import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "record-*.spec.ts",
  timeout: 180000,
  retries: 0,
  reporter: "list",
  use: {
    browserName: "chromium",
  },
});
