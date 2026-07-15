import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: 'tests/e2e',
  // Run this config from frontend/ (the package's test:e2e script).  The
  // relative cwd values keep the Vite and FastAPI commands tied to this
  // repository rather than whichever directory launched Playwright.
  webServer: [
    {
      command: 'npm run dev -- --host 0.0.0.0 --port 5173',
      port: 5173,
      reuseExistingServer: true,
      cwd: '.',
    },
    {
      command: '../.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000',
      port: 8000,
      reuseExistingServer: true,
      cwd: '..',
    },
  ],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
