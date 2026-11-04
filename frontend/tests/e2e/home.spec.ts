import { expect, test } from "@playwright/test";

test("the overview renders the service status panel", async ({ page }) => {
  const response = await page.goto("/");

  expect(response?.status()).toBe(200);
  await expect(
    page.getByRole("heading", { name: "Trendsmapp", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Service status" }),
  ).toBeVisible();
});

test("the navigation reaches the methods and privacy pages", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "Methods" }).click();
  await page.waitForURL("**/methods");
  await expect(
    page.getByRole("heading", { name: "Methods", level: 1 }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Privacy" }).click();
  await page.waitForURL("**/privacy");
  await expect(
    page.getByRole("heading", { name: "Privacy", level: 1 }),
  ).toBeVisible();
});
