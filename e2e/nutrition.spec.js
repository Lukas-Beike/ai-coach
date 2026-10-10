const { test, expect } = require("@playwright/test");

test("@responsive nutrition diary and saved meals remain read-only and preserve confirmed consumption", async ({ page }) => {
  const showNutrition = async (route) => {
    await page.evaluate((nextRoute) => AppRouter.navigate(nextRoute, { historyMode: "push" }), route);
    await expect(page.locator("#nutritionStatus")).not.toContainText("wird geladen");
  };
  await page.goto("/#nutrition/diary");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#nutritionStatus")).not.toContainText("wird geladen");
  await expect(page.locator("#nutritionEntries .nutrition-card")).toHaveCount(0);
  await expect(page.locator("#nutritionTotals")).toContainText("– kcal");
  await page.locator('[data-nutrition-segment="meals"]').click();
  await expect(page.locator("#nutritionDefine, #nutritionLog, #trainingFueling")).toHaveCount(0);
  const send = async (text) => {
    await page.locator('a[href="#coach"]:visible').first().click();
    await page.locator("#messageInput").fill(text);
    await page.locator("#sendButton").click();
    await expect.poll(() => page.evaluate(() => !state.busy && !state.chatServerOperationId && !state.chatRequest)).toBe(true);
  };
  await send("E2E nutrition: confirm meal");
  await expect(page.locator("#coachActionReview")).toBeVisible();
  await page.locator("#coachActionReview").getByRole("button", { name: "Mahlzeitvorlage speichern" }).click();
  await expect(page.locator("#coachActionReview")).toBeHidden();
  await showNutrition("nutrition/meals");
  await expect(page.locator("#nutritionTemplates .nutrition-card")).toHaveCount(1);
  await expect(page.locator("#nutritionTemplates")).toContainText("400 kcal");
  await expect(page.locator("#nutritionTemplates img")).toHaveCount(0);
  await page.locator('[data-nutrition-segment="diary"]').click();
  await expect(page.locator("#nutritionEntries .nutrition-card")).toHaveCount(0);
  await send("E2E nutrition: half portion");
  await showNutrition("nutrition/diary");
  await expect(page.locator("#nutritionEntries .nutrition-card")).toHaveCount(1);
  await expect(page.locator("#nutritionTotals")).toContainText("200 kcal");
  await page.locator('[data-nutrition-segment="meals"]').click();
  await send("E2E nutrition: update meal");
  await expect(page.locator("#coachActionReview")).toBeVisible();
  await page.locator("#coachActionReview").getByRole("button", { name: "Mahlzeitvorlage speichern" }).click();
  await expect(page.locator("#coachActionReview")).toBeHidden();
  await showNutrition("nutrition/meals");
  await expect(page.locator("#nutritionTemplates")).toContainText("600 kcal");
  await send("E2E nutrition: delete meal");
  await showNutrition("nutrition/diary");
  await expect(page.locator("#nutritionTotals")).toContainText("200 kcal");
  await page.locator("#nutritionPrevious").click();
  await expect(page.locator("#nutritionEntries .nutrition-card")).toHaveCount(0);
  await page.locator("#nutritionToday").click();
  await expect(page.locator("#nutritionEntries .nutrition-card")).toHaveCount(1);
  await page.evaluate(() => { document.querySelector("#messageInput").value = "Existing draft"; });
  await expect(page.locator("#messageInput")).toHaveValue("Existing draft");
  await page.evaluate(() => { document.querySelector("#messageInput").value = ""; });
  await page.goto("/#nutrition/diary");
  await expect(page.locator("#nutritionTotals")).toContainText("200 kcal");
  await send("E2E nutrition: database oats");
  await showNutrition("nutrition/diary");
  const databaseCard = page.locator("#nutritionEntries .nutrition-card").filter({ hasText: "50 g Haferflocken" });
  await expect(databaseCard).toContainText("174 kcal");
  await expect(databaseCard).toContainText("Datenbankberechnung");
  await expect(databaseCard).toContainText("Max Rubner-Institut");
  await expect(databaseCard).toContainText("50 g (Basis 100 g)");
  await page.reload();
  await expect(databaseCard).toContainText("174 kcal");
  await expect(databaseCard).toContainText("Datenbankberechnung");
  await page.locator('[data-nutrition-segment="meals"]').click();
  await send("E2E nutrition: confirm database meal");
  await expect(page.locator("#coachActionReview")).toContainText("174");
  await expect(page.locator("#coachActionReview")).toContainText("Max Rubner-Institut");
  await page.locator("#coachActionReview").getByRole("button", { name: "Mahlzeitvorlage speichern" }).click();
  await expect(page.locator("#coachActionReview")).toBeHidden();
  await showNutrition("nutrition/meals");
  await expect(page.locator("#nutritionTemplates")).toContainText("174 kcal");
  await expect(page.locator("#nutritionTemplates")).toContainText("Datenbankberechnung");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive nutrition product library supports review, local save, and preserving an existing Coach draft", async ({ page }) => {
  const productName = `Fixture Whey ${Date.now()}`;
  const barcode = String(Date.now()).slice(-13);
  await page.goto("/#nutrition/products");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.locator("#nutritionProductManual").click();
  const editor = page.locator("#nutritionExtraction");
  await expect(editor).toBeVisible();
  await editor.locator('[name="name"]').fill(productName);
  await editor.locator('[name="brand"]').fill("Fixture");
  await editor.locator('[name="barcode"]').fill(barcode);
  await editor.locator('[name="kcal"]').fill("380");
  await editor.locator('[name="protein_g"]').fill("72");
  await editor.locator('[name="basis_amount"]').fill("100");
  await editor.locator('[name="basis_unit"]').selectOption("g");
  await editor.getByRole("button", { name: "Produkt lokal speichern" }).click();
  let card = page.locator("#nutritionProducts .nutrition-product-card").filter({ hasText: productName });
  await expect(card).toContainText("380 kcal");
  await page.reload();
  card = page.locator("#nutritionProducts .nutrition-product-card").filter({ hasText: productName });
  await expect(card).toContainText("72 g");

  await card.getByRole("button", { name: "Bearbeiten" }).click();
  await editor.locator('[name="protein_g"]').fill("73");
  await editor.getByRole("button", { name: "Produkt lokal speichern" }).click();
  card = page.locator("#nutritionProducts .nutrition-product-card").filter({ hasText: productName });
  await expect(card).toContainText("73 g");

  await page.evaluate(() => {
    const input = document.querySelector("#messageInput");
    input.value = "Bestehender Entwurf";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await card.getByRole("button", { name: "In Mahlzeit erfassen" }).click();
  await page.locator("#nutritionProductUseAmount").fill("25");
  await page.locator("#nutritionProductUseForm").getByRole("button", { name: "Coach-Entwurf erstellen" }).click();
  await expect(page.locator("#confirmationDialog")).toBeVisible();
  await page.locator("#confirmationDialogCancel").click();
  await expect.poll(() => page.locator("#messageInput").evaluate((input) => input.value)).toBe("Bestehender Entwurf");
  await expect(page.locator("#nutritionProductUseDialog")).toBeVisible();
  await page.locator("#nutritionProductUseCancel").click();

  await card.getByRole("button", { name: "Archivieren" }).click();
  await expect(page.locator("#confirmationDialog")).toBeVisible();
  await page.locator("#confirmationDialogAccept").click();
  await expect(page.locator("#nutritionProducts .nutrition-product-card").filter({ hasText: productName })).toHaveCount(0);
});

test("@responsive packaging extraction requires editable basis values before explicit local save", async ({ page }) => {
  const onePixel = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
  let savedPayload;
  let extractionPayload;
  await page.route("**/api/nutrition/products**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") return route.fulfill({ json: { ok: true, products: [] } });
    savedPayload = request.postDataJSON();
    return route.fulfill({ json: { ok: true, product: { ...savedPayload, id: "product-photo-1", local: true } } });
  });
  await page.route("**/api/nutrition/products/extract", async (route) => {
    extractionPayload = route.request().postDataJSON();
    return route.fulfill({ json: {
      ok: true,
      candidate: { name: "Foto Protein", kcal: 180, protein_g: 30, carbs_g: null, fat_g: null },
      provenance: { kind: "packaging_label", requires_confirmation: true },
    } });
  });
  await page.goto("/#nutrition/products");
  await page.locator("#nutritionLabelInput").setInputFiles({ name: "label.jpg", mimeType: "image/jpg", buffer: onePixel });
  await expect.poll(() => extractionPayload?.image_data_url).toMatch(/^data:image\/jpeg;base64,/);
  const editor = page.locator("#nutritionExtraction");
  await expect(editor).toBeVisible();
  await expect(editor.locator('[name="basis_amount"]')).toHaveValue("");
  await expect(editor.locator('[name="basis_unit"]')).toHaveValue("");
  await editor.getByRole("button", { name: "Produkt lokal speichern" }).click();
  await expect.poll(() => savedPayload).toBeUndefined();
  await editor.locator('[name="basis_amount"]').fill("100");
  await editor.locator('[name="basis_unit"]').selectOption("g");
  await editor.getByRole("button", { name: "Produkt lokal speichern" }).click();
  await expect.poll(() => savedPayload?.name).toBe("Foto Protein");
  expect(savedPayload.source).toBe("packaging_label");
  expect(savedPayload.provenance.kind).toBe("packaging_label");
});

test("@responsive closing the barcode dialog stops a late Android Chromium camera stream", async ({ page }) => {
  await page.addInitScript(() => {
    window.__nutritionCamera = { resolve: null, stopped: 0 };
    const mediaDevices = navigator.mediaDevices || {};
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: mediaDevices });
    Object.defineProperty(mediaDevices, "getUserMedia", {
      configurable: true,
      value: () => new Promise((resolve) => { window.__nutritionCamera.resolve = resolve; }),
    });
    window.BarcodeDetector = class { constructor() {} async detect() { return []; } };
  });
  await page.goto("/#nutrition/products");
  await page.locator("#nutritionBarcodeButton").click();
  await expect(page.locator("#nutritionBarcodeDialog")).toBeVisible();
  await page.locator("#nutritionBarcodeCancel").click();
  await page.evaluate(() => window.__nutritionCamera.resolve({ getTracks: () => [{ stop: () => { window.__nutritionCamera.stopped += 1; } }] }));
  await expect.poll(() => page.evaluate(() => window.__nutritionCamera.stopped)).toBe(1);
  await expect(page.locator("#nutritionBarcodeDialog")).toBeHidden();
});

test("@responsive Open Food Facts lookup can be explicitly saved into the local product library", async ({ page }) => {
  let savedPayload;
  let lookupCount = 0;
  await page.route("**/api/nutrition/products**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "GET") return route.fulfill({ json: { ok: true, products: [] } });
    if (path.endsWith("/lookup")) {
      lookupCount += 1;
      if (lookupCount > 1) return route.fulfill({ json: { ok: true, source: "manual", local: true, product: { ...savedPayload, id: "product-off-local" } } });
      return route.fulfill({ json: {
        ok: true, source: "open_food_facts", local: false,
        product: { id: "off:4006381333931", name: "Bio Haferdrink", brands: "Beispiel", per_100: { kcal: 46, carbs_g: 6.7, protein_g: 1, fat_g: 1.5 }, basis_amount: 100, basis_unit: "ml", source: "open_food_facts", source_url: "https://world.openfoodfacts.org/product/4006381333931" },
      } });
    }
    savedPayload = request.postDataJSON();
    return route.fulfill({ json: { ok: true, product: { ...savedPayload, id: "product-off-local", local: true } } });
  });
  await page.addInitScript(() => { window.BarcodeDetector = undefined; });
  await page.goto("/#nutrition/products");
  await page.locator("#nutritionBarcodeButton").click();
  await expect(page.locator("#nutritionBarcodeDialog")).toBeVisible();
  await page.locator("#nutritionBarcodeManual").fill("4006381333931");
  await page.locator("#nutritionBarcodeLookup").click();
  await expect(page.locator("#nutritionExtraction")).toBeVisible();
  const editor = page.locator("#nutritionExtraction");
  await expect(editor.locator('[name="name"]')).toHaveValue("Bio Haferdrink");
  await expect(editor.locator('[name="barcode"]')).toHaveValue("4006381333931");
  await editor.getByRole("button", { name: "Produkt lokal speichern" }).click();
  await expect.poll(() => savedPayload?.name).toBe("Bio Haferdrink");
  expect(savedPayload.source).toBe("open_food_facts");
  expect(savedPayload.external_id).toBe("off:4006381333931");
  expect(savedPayload.barcode).toBe("4006381333931");
  await page.locator("#nutritionBarcodeButton").click();
  await page.locator("#nutritionBarcodeManual").fill("4006381333931");
  await page.locator("#nutritionBarcodeLookup").click();
  await expect(page.locator("#nutritionProductStatus")).toContainText("Lokales Produkt gefunden");
  expect(lookupCount).toBe(2);
});

test("@responsive a small undecodable image falls back to attachment and allows a valid image afterwards", async ({ page }) => {
  const validPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(() => jumpToLatestMessages());
  await page.locator("#attachmentInput").setInputFiles({ name: "broken.png", mimeType: "image/png", buffer: Buffer.from("not an image") });
  await expect(page.locator("#chatAttachments")).toContainText("broken.png");
  await expect(page.locator("#sendButton")).toBeEnabled();
  await page.locator("#attachmentInput").setInputFiles({ name: "label.png", mimeType: "image/png", buffer: validPng });
  await expect(page.locator("#chatAttachments")).toContainText("label.png");
  await expect(page.locator("#sendButton")).toBeEnabled();
});

test("@responsive composite meal shows immutable ingredient snapshots and provenance", async ({ page }) => {
  await page.goto("/#nutrition/diary");
  const initialEntries = await page.evaluate(async () => (await api("/api/nutrition/day")).entry_count);
  await page.goto("/#coach");
  await page.locator("#messageInput").fill("E2E nutrition: mixed meal");
  await page.locator("#sendButton").click();
  await expect.poll(() => page.evaluate(() => !state.busy && !state.chatServerOperationId && !state.chatRequest)).toBe(true);
  await expect.poll(() => page.evaluate(async () => (await api("/api/nutrition/day")).entry_count)).toBe(initialEntries + 1);
  await page.goto("/#nutrition/diary");
  const card = page.locator("#nutritionEntries .nutrition-card").filter({ hasText: "Mixed meal" });
  await expect(card).toHaveCount(1);
  await expect(card).toContainText("kcal");
  await card.locator("summary").click();
  await expect(card).toContainText("Synthetic whey");
  await expect(card).toContainText("Max Rubner-Institut");
  await expect(card).toContainText("Hafer Flocken");
  await expect(card).toContainText("Verpackungsangabe");
  await expect(card).toContainText("Creatine");
  await expect(card.locator("img")).toHaveCount(0);
  await page.reload();
  await expect(page.locator("#nutritionEntries .nutrition-card").filter({ hasText: "Mixed meal" })).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
