import { expect, test } from "@playwright/test";
import path from "node:path";

const FIXTURE = path.resolve(import.meta.dirname, "../fixtures/sample.csv");

test("a file is uploaded, mapped, ingested, and sealed end to end", async ({ page }) => {
  await page.goto("/upload");

  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles(FIXTURE);

  // The probe appears once the upload completes, offering the mapping form.
  await expect(page.getByText(/detected csv layout/i)).toBeVisible({ timeout: 30_000 });

  // Confirm the proposed mapping and create the dataset.
  await page.getByRole("button", { name: /confirm mapping/i }).click();
  await expect(page.getByText(/ingest job/i)).toBeVisible({ timeout: 30_000 });

  // The worker seals the version; the page announces it.
  await expect(page.getByText(/dataset version sealed/i)).toBeVisible({ timeout: 60_000 });

  await page.getByRole("link", { name: /open the dataset/i }).click();
  await expect(page).toHaveURL(/\/datasets\/ds_/);
  await expect(page.getByRole("heading", { name: "sample.csv" })).toBeVisible();

  // The version explorer shows the sealed version; open the preview tab.
  await expect(page.getByText(/2 stations · 2 parameters/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("tab", { name: "Preview" }).click();
  await expect(page.getByRole("columnheader", { name: "observation_id" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByRole("tab", { name: "Quality control" })).toBeVisible();
});
