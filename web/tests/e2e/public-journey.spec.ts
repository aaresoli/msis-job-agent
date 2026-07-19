import { expect, test } from "@playwright/test";

test("student can reach the private sign-in experience", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Your search",
  );
  await page.getByRole("link", { name: /open your desk/i }).click();
  await expect(page).toHaveURL(/\/auth\/login/);
  await expect(page.getByLabel(/email/i)).toBeVisible();
});

test("PWA does not register a private-data service worker", async ({ page }) => {
  await page.goto("/");
  const registrations = await page.evaluate(async () =>
    "serviceWorker" in navigator
      ? (await navigator.serviceWorker.getRegistrations()).length
      : 0,
  );
  expect(registrations).toBe(0);
});
