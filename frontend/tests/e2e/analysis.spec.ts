import { expect, test } from "@playwright/test";
import path from "node:path";

const FIXTURE = path.resolve(import.meta.dirname, "../fixtures/analysis.csv");

// The analysis runs the full pipeline in the worker; allow it several minutes.
test.setTimeout(300_000);

test("analyze a dataset and render an animation end to end", async ({
  page,
}) => {
  await page.goto("/upload");
  await page.locator('input[type="file"]').setInputFiles(FIXTURE);
  await expect(page.getByText(/detected csv layout/i)).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: /confirm mapping/i }).click();
  await expect(page.getByText(/dataset version sealed/i)).toBeVisible({
    timeout: 60_000,
  });
  await page.getByRole("link", { name: /open the dataset/i }).click();
  await expect(page).toHaveURL(/\/datasets\/ds_/);

  await page.getByRole("tab", { name: "Analyze" }).click();
  await page.getByRole("button", { name: /run analysis/i }).click();

  // The run completes and the results table shows the IDW frame.
  await expect(page.getByText(/\d+ frames · grid/)).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByRole("cell", { name: "idw" }).first()).toBeVisible();

  // Create the animation and wait for the video player.
  await page.getByRole("button", { name: /create animation/i }).click();
  await expect(page.getByText(/animation/i).first()).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.locator("video")).toBeVisible({ timeout: 90_000 });
});
