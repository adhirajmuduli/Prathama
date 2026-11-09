import { expect, test } from "@playwright/test";
import path from "node:path";

const FIXTURE = path.resolve(import.meta.dirname, "../fixtures/ml.csv");

// Training runs the full cross-validation loop in the worker; allow minutes.
test.setTimeout(600_000);

test("train a model run, read its results, and export the bundle", async ({
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

  await page.getByRole("tab", { name: "Model" }).click();
  await page.getByRole("button", { name: /train model run/i }).click();

  // The comparison table appears once the training job succeeds.
  await expect(page.getByText(/selected family/)).toBeVisible({
    timeout: 300_000,
  });
  await expect(
    page.getByRole("cell", { name: "elastic_net" }).first(),
  ).toBeVisible();
  await expect(page.getByText(/empirical coverage/)).toBeVisible();
  await expect(page.getByText(/held-out predictions:/i)).toBeVisible();
  // Explanations render with the recorded non-causal disclaimer.
  await expect(page.getByText(/not causal effects/)).toBeVisible();

  // Export the succeeded run and get the verified bundle download.
  await page.getByRole("button", { name: /export bundle/i }).click();
  await expect(page.getByRole("link", { name: /download zip/i })).toBeVisible({
    timeout: 120_000,
  });
  await expect(page.getByText(/trendsmapp reproduce/)).toBeVisible();
});
