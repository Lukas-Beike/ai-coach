const { test, expect } = require("@playwright/test");

test("attachments can be removed, rejected and sent with an empty text draft", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(() => jumpToChatComposer());
  await expect(page.locator("#attachmentButton")).toHaveText("+");
  await expect(page.locator("#attachmentButton")).toHaveAttribute("aria-label", "GPX- oder FIT-Dateien oder Bilder anhängen");
  const file = { name: "route.gpx", mimeType: "application/gpx+xml", buffer: Buffer.from('<gpx><rte><rtept lat="0" lon="0"/><rtept lat="0" lon="0.01"/></rte></gpx>') };
  await page.locator("#attachmentInput").setInputFiles(file);
  await expect(page.locator("#chatAttachments")).toContainText("route.gpx");
  await expect(page.locator("#sendButton")).toBeEnabled();
  await page.locator("#chatAttachments button").click();
  await expect(page.locator("#chatAttachments")).toBeHidden();
  await expect(page.locator("#sendButton")).toBeDisabled();
  await page.locator("#attachmentInput").setInputFiles({ ...file, buffer: Buffer.from('invalid GPX') });
  await page.locator("#sendButton").click();
  await expect(page.locator("#chatAttachments")).toContainText("route.gpx");
  await expect(page.locator("#sendButton")).toBeEnabled();
  await page.locator("#chatAttachments button").click();
  await page.locator("#messageInput").fill("");
  await page.locator("#attachmentInput").setInputFiles([file, { name: "chart.png", mimeType: "image/png", buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aFOsAAAAASUVORK5CYII=', 'base64') }]);
  await expect(page.locator("#chatAttachments button")).toHaveCount(2);
  await page.locator("#sendButton").click();
  await expect(page.locator("#chatAttachments")).toBeHidden();
  await expect(page.locator("#messages")).toContainText("chart.png");
  await page.reload();
  await expect(page.locator("#messages")).toContainText("route.gpx");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
});

test("attachments stay with their own queued message", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(() => jumpToChatComposer());
  const requests = [];
  let releaseFirst;
  const gate = new Promise(resolve => { releaseFirst = resolve; });
  await page.route("**/api/chat/stream", async route => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) await gate;
    await route.continue();
  });
  const file = name => ({ name, mimeType: "application/gpx+xml", buffer: Buffer.from('<gpx><rte><rtept lat="0" lon="0"/></rte></gpx>') });
  await page.locator("#messageInput").fill("First route");
  await page.locator("#attachmentInput").setInputFiles(file("first.gpx"));
  await page.locator("#sendButton").click();
  await expect.poll(() => requests.length).toBe(1);
  await page.locator("#messageInput").fill("Second route");
  await page.locator("#attachmentInput").setInputFiles(file("second.gpx"));
  await page.locator("#sendButton").click();
  releaseFirst();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests.map(request => [request.message, request.attachments[0].name])).toEqual([
    ["First route", "first.gpx"], ["Second route", "second.gpx"],
  ]);
});
