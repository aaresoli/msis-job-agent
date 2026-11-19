import { defineConfig, devices } from "@playwright/test";

// The port is configurable so the suite does not collide with whatever else a
// developer happens to have on 3000. The webServer and the baseURL have to
// agree, so both derive from the same value.
const port = Number(process.env.PLAYWRIGHT_PORT ?? 3000);
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  webServer: {
    // CI exercises the production build; locally `dev` keeps the loop fast.
    // `next start` warns that it ignores `output: "standalone"` (which exists
    // for the Docker image) and serves from .next instead. That is the correct
    // target here: these specs assert public page behavior, not the packaging.
    command: process.env.CI
      ? `npm run start -- --port ${port}`
      : `npm run dev -- --port ${port}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["iPhone 13"] } },
  ],
});
