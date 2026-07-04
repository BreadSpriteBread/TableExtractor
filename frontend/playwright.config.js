// E2E config: boots the Flask backend on a throwaway DB and the Vite dev
// server, then runs the happy-path spec against the real stack.
import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const e2eTmp = mkdtempSync(join(tmpdir(), 'thesis-e2e-'))

export default defineConfig({
  testDir: './e2e',
  timeout: 300_000,  // extraction pays a docling model load per document
  use: {
    // 5174 so E2E never collides with a developer's own dev server on 5173
    baseURL: 'http://localhost:5174',
  },
  webServer: [
    {
      command: 'python3 -m backend.app',
      cwd: '..',
      port: 5000,
      reuseExistingServer: false,
      env: {
        THESIS_DB_PATH: join(e2eTmp, 'e2e.db'),
        THESIS_UPLOAD_DIR: join(e2eTmp, 'uploads'),
        THESIS_PDF_DIR: join(e2eTmp, 'no_corpus'),
        SCRAPER_STUB: '1',
        FLASK_DEBUG: '0',  // no reloader: E2E needs one stable process
      },
    },
    {
      command: 'npm run dev -- --port 5174 --strictPort',
      port: 5174,
      reuseExistingServer: false,
    },
  ],
})
