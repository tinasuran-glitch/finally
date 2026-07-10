import { defineConfig, devices } from "@playwright/test";

const BASE_URL = "http://127.0.0.1:8001";

// The app carries cumulative DB state across tests within a single run, so the
// suite runs serially with a single worker. Spec files are numbered to keep the
// fresh-start assertions (which require the untouched $10k / no-position seed)
// running before any trade mutates state.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    // Force-recreate guarantees a fresh ephemeral DB even if a container from a
    // prior run is still around. Foreground `up` streams logs; Playwright sends
    // SIGINT on teardown, which compose handles by stopping the container.
    command:
      "docker compose -f docker-compose.test.yml up --force-recreate --remove-orphans",
    url: `${BASE_URL}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
