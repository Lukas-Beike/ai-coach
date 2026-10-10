const { test, expect } = require("@playwright/test");

test("queued coach follow-ups keep order, can be edited or removed without browser persistence @responsive", async ({ page }) => {
  // This runtime has no slow-stream fixture trigger, so the stream request is held open in the browser.
  // A held request never reaches the server, so no answer is recorded and nothing is sent after the test.
  await page.route("**/api/chat/stream", () => new Promise(() => {}));
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/#coach");
  await expect(page.locator("#loginDialog")).toBeHidden();
  await page.waitForFunction(() => state.initialStateLoaded);

  const input = page.locator("#messageInput");
  const send = page.locator("#sendButton");
  await input.fill("E2E fixture: slow stream");
  await send.click();
  await expect(page.locator("#steerButton")).toBeVisible();
  await expect(input).toHaveAttribute("placeholder", "Folgefrage – wird danach gesendet");
  await expect(page.locator("#steerButton")).toBeDisabled();
  await expect(page.locator("#steerButtonHint")).toHaveText("Schreibe zuerst eine Nachricht, um sie als Nächstes zu senden.");

  for (const text of ["Erste Folgefrage", "Zweite Folgefrage"]) {
    await input.fill(text);
    await send.click();
  }
  const queued = page.locator(".message.pending");
  await expect(queued).toHaveCount(2);
  await expect(queued.nth(0)).toContainText("Erste Folgefrage");
  await expect(queued.nth(0).locator(".pending-label")).toHaveText("Als Nächstes");
  await expect(queued.nth(1)).toContainText("Zweite Folgefrage");
  await expect(queued.nth(1).locator(".pending-label")).toHaveText("Wird nach der aktuellen Antwort gesendet");

  await page.getByRole("button", { name: "Entfernen: wartende Nachricht 1" }).click();
  await expect(queued).toHaveCount(1);
  await expect(queued.first()).toContainText("Zweite Folgefrage");
  await expect(queued.first().locator(".pending-label")).toHaveText("Als Nächstes");

  await input.fill("Dritte Folgefrage");
  await send.click();
  await expect(queued).toHaveCount(2);
  await input.fill("Entwurf");
  await page.getByRole("button", { name: "Bearbeiten: wartende Nachricht 1" }).click();
  await expect(queued).toHaveCount(1);
  await expect(queued.first()).toContainText("Dritte Folgefrage");
  await expect(input).toHaveValue("Entwurf\nZweite Folgefrage");

  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(stored).not.toContain("Folgefrage");
});
