import { expect, test } from "@playwright/test";

// The widget uses Cloudflare's always-pass test site key in E2E. The happy
// path additionally needs real Upstash/Resend test credentials, which CI
// provides; without them the route answers 503 and the form shows that.
const hasProviders = Boolean(process.env.CONTACT_E2E_PROVIDERS);

test.setTimeout(120_000);

test("contact form renders and requires the human check before sending", async ({
  page,
}) => {
  await page.goto("/contact");
  await expect(page.getByRole("heading", { name: "Contact" })).toBeVisible();
  const submit = page.getByRole("button", { name: /send message/i });
  // No token yet: the button stays disabled.
  await expect(submit).toBeDisabled();
});

test("contact form validates required fields", async ({ page }) => {
  await page.goto("/contact");
  // Wait for the Turnstile test widget to produce a token.
  const submit = page.getByRole("button", { name: /send message/i });
  await expect(submit).toBeEnabled({ timeout: 60_000 });
  await page.getByRole("button", { name: /send message/i }).click();
  await expect(page.getByText(/the message was not sent/i)).toBeVisible({
    timeout: 10_000,
  });
});

test("contact submission reports when the deployment is not configured", async ({
  page,
}) => {
  test.skip(
    hasProviders,
    "provider-backed happy path runs when credentials exist",
  );
  await page.goto("/contact");
  await page.getByLabel("Name", { exact: true }).fill("Ada Lovelace");
  await page.getByLabel("Email", { exact: true }).fill("ada@example.org");
  await page.getByLabel("Subject", { exact: true }).fill("Question");
  await page
    .getByLabel("Message", { exact: true })
    .fill("A sufficiently long message body.");
  await page.getByRole("checkbox").check();
  const submit = page.getByRole("button", { name: /send message/i });
  await expect(submit).toBeEnabled({ timeout: 60_000 });
  await submit.click();
  await expect(page.getByText(/could not be sent|not available/i)).toBeVisible({
    timeout: 30_000,
  });
});

test("contact submission succeeds with provider test credentials", async ({
  page,
}) => {
  test.skip(
    !hasProviders,
    "needs CONTACT_E2E_PROVIDERS with Upstash/Resend test credentials",
  );
  await page.goto("/contact");
  await page.getByLabel("Name", { exact: true }).fill("Ada Lovelace");
  await page.getByLabel("Email", { exact: true }).fill("ada@example.org");
  await page.getByLabel("Subject", { exact: true }).fill("E2E question");
  await page
    .getByLabel("Message", { exact: true })
    .fill("A sufficiently long message body.");
  await page.getByRole("checkbox").check();
  const submit = page.getByRole("button", { name: /send message/i });
  await expect(submit).toBeEnabled({ timeout: 60_000 });
  await submit.click();
  await expect(page.getByText(/message sent/i)).toBeVisible({
    timeout: 30_000,
  });
});
