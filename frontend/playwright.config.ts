import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";
const apiURL = process.env.PLAYWRIGHT_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  // The ML spec trains real models (minutes per attempt); never retry it.
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"]],
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: [
    {
      name: "backend",
      // Cross-platform launcher: the venv entry point on Windows, `uv run`
      // elsewhere so CI needs no pre-created venv path.
      command:
        process.platform === "win32"
          ? "..\\backend\\.venv\\Scripts\\trendsmapp.exe dev --host 127.0.0.1 --port 8000"
          : "uv run --project . trendsmapp dev --host 127.0.0.1 --port 8000",
      cwd: "../backend",
      url: `${apiURL}/api/v1/health/live`,
      // Always start a fresh backend: a reused one may hold a stale database.
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        TRENDSMAPP_ENVIRONMENT: "development",
        TRENDSMAPP_DATABASE_URL: "sqlite+aiosqlite:///./e2e.db",
        TRENDSMAPP_LOCAL_STORAGE_ROOT: "./var/e2e-objects",
        TRENDSMAPP_CORS_ALLOW_ORIGINS:
          '["http://127.0.0.1:3000","http://localhost:3000"]',
        TRENDSMAPP_LOG_LEVEL: "warning",
      },
    },
    {
      name: "frontend",
      command: "pnpm run build && pnpm run start",
      url: baseURL,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      env: {
        NEXT_PUBLIC_API_BASE_URL: apiURL,
        NEXT_PUBLIC_SITE_URL: baseURL,
        BACKEND_API_ORIGIN: apiURL,
        // Cloudflare's always-pass test site key for the E2E contact form.
        NEXT_PUBLIC_TURNSTILE_SITE_KEY: "1x00000000000000000000AA",
      },
    },
  ],
});
