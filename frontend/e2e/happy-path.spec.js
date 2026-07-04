// Full happy path: upload -> cart -> extract -> view -> export -> history.
import { expect, test } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FIXTURE = path.resolve(__dirname, '../../tests/fixtures/pdfs/simple.pdf')

test('upload → cart → extract → view → export → history', async ({ page }) => {
  await page.goto('/')

  // ---- Acquire: upload a PDF
  await page.getByRole('tab', { name: 'Acquire Reports' }).click()
  await page.getByTestId('upload-input').setInputFiles(FIXTURE)
  await expect(page.getByText('simple.pdf')).toBeVisible()

  // ---- Add to cart; badge updates everywhere
  await page.getByRole('button', { name: 'Add to cart' }).click()
  await expect(page.getByTestId('cart-badge')).toContainText('1')

  // ---- Extract Results: run extraction and wait for Done
  await page.getByRole('tab', { name: 'Extract Results' }).click()
  await expect(page.getByText('simple.pdf')).toBeVisible()
  await page.getByRole('button', { name: /Extract all/ }).click()
  // Generous: the extraction child process loads docling's models first
  await expect(page.locator('[data-status="success"]')).toBeVisible({ timeout: 180_000 })
  await expect(page.getByTestId('batch-progress')).toContainText('1/1')

  // ---- View the extracted table
  await page.getByRole('button', { name: 'View' }).click()
  await expect(page.getByRole('dialog')).toContainText('Revenue')
  await expect(page.getByRole('dialog')).toContainText('2200')
  await page.getByRole('button', { name: 'Close' }).click()

  // ---- Export JSON (download with correct bundle shape)
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export JSON' }).click()
  const download = await downloadPromise
  const stream = await download.createReadStream()
  const chunks = []
  for await (const c of stream) chunks.push(c)
  const bundle = JSON.parse(Buffer.concat(chunks).toString('utf-8'))
  expect(bundle.documents).toHaveLength(1)
  expect(bundle.documents[0].document_id).toMatch(/^sha256:/)
  expect(bundle.documents[0].status).toBe('success')
  expect(bundle.documents[0].tables[0].headers).toEqual(['Item', 'Q1', 'Q2', 'Total'])

  // ---- History: find it via search
  await page.getByRole('tab', { name: 'Extracted Tables' }).click()
  await page.getByLabel('Filename contains').fill('simple')
  await page.getByRole('button', { name: 'Search' }).click()
  const row = page.getByRole('row', { name: /simple\.pdf/ })
  await expect(row).toBeVisible()
  await expect(row.locator('[data-status="success"]')).toBeVisible()

  // full-text search over cell content also finds it
  await page.getByLabel('Full-text (headers & cells)').fill('Revenue')
  await page.getByRole('button', { name: 'Search' }).click()
  await expect(page.getByRole('row', { name: /simple\.pdf/ })).toBeVisible()
})
