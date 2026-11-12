const { test, expect } = require("@playwright/test");
const { waitForSettledState } = require("./helpers/settled-state");

const productSection = (page, key) => page.locator(`#nutritionProducts details[data-section="${key}"]`);

// Opens a product section and returns its cards.
async function openProductSection(page, key) {
  const section = productSection(page, key);
  await expect(section).toBeAttached();
  if (!await section.evaluate((node) => node.open)) await section.locator("summary").click();
  await expect(section).toHaveAttribute("open", "");
  return section.locator(".nutrition-product-card");
}

test("@responsive nutrition diary and saved meals remain read-only and preserve confirmed consumption", async ({ page }) => {
  const showNutrition = async (route) => {
    await page.evaluate((nextRoute) => AppRouter.navigate(nextRoute, { historyMode: "push" }), route);
    await expect(page.locator("#nutritionStatus")).not.toContainText("wird geladen");
  };
  await page.goto("/#nutrition/diary");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#nutritionStatus")).not.toContainText("wird geladen");
  await expect(page.locator("#nutritionEntries .nutrition-card")).toHaveCount(0);
  await expect(page.locator("#nutritionTotals strong.value-missing")).toHaveCount(6);
  await expect(page.locator("#nutritionTotals strong.value-missing").first()).toHaveText("nicht erfasst");
  await expect(page.locator('[data-nutrition-segment="meals"], #nutritionMeals, #nutritionTemplates')).toHaveCount(0);
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
  await expect(page.locator('[data-nutrition-segment="diary"]')).toHaveAttribute("aria-current", "page");
  await page.locator('[data-nutrition-segment="diary"]').click();
  await expect(page.locator("#nutritionEntries .nutrition-card")).toHaveCount(0);
  await send("E2E nutrition: half portion");
  await showNutrition("nutrition/diary");
  await expect(page.locator("#nutritionEntries .nutrition-card")).toHaveCount(1);
  await expect(page.locator("#nutritionTotals")).toContainText("200 kcal");
  await send("E2E nutrition: update meal");
  await expect(page.locator("#coachActionReview")).toBeVisible();
  await page.locator("#coachActionReview").getByRole("button", { name: "Mahlzeitvorlage speichern" }).click();
  await expect(page.locator("#coachActionReview")).toBeHidden();
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
  await send("E2E nutrition: confirm database meal");
  await expect(page.locator("#coachActionReview")).toContainText("174");
  await expect(page.locator("#coachActionReview")).toContainText("Max Rubner-Institut");
  await page.locator("#coachActionReview").getByRole("button", { name: "Mahlzeitvorlage speichern" }).click();
  await expect(page.locator("#coachActionReview")).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive nutrition product library supports review, local save, favorites, and extending an existing Coach draft", async ({ page }) => {
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
  await expect(page.locator("#nutritionProductStatus")).toContainText("lokal gespeichert");
  await page.reload();
  await expect(productSection(page, "favorites")).not.toHaveAttribute("open", "");
  await expect(productSection(page, "all")).not.toHaveAttribute("open", "");
  const cards = await openProductSection(page, "all");
  let card = cards.filter({ hasText: productName });
  await expect(card).toContainText("72 g");
  await expect(card).toContainText("eigen");
  await expect(card).toContainText("fehlt: Kohlenhydrate");

  await card.getByRole("button", { name: "Bearbeiten" }).click();
  await editor.locator('[name="protein_g"]').fill("73");
  await editor.getByRole("button", { name: "Produkt lokal speichern" }).click();
  await expect(card).toContainText("73 g");

  await page.evaluate(() => {
    const input = document.querySelector("#messageInput");
    input.value = "Bestehender Entwurf";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await card.getByRole("button", { name: "Verwenden" }).click();
  await page.locator("#nutritionProductUseAmount").fill("25");
  await page.locator("#nutritionProductUseCoach").click();
  await expect.poll(() => page.locator("#messageInput").evaluate((input) => input.value)).toMatch(/^Bestehender Entwurf\nDazu 25 g \(Produkt-ID: /);
  await page.goto("/#nutrition/products");
  await page.reload();
  await openProductSection(page, "all");
  await card.getByRole("button", { name: "Verwenden" }).click();
  await page.locator("#nutritionProductUseAmount").fill("50");
  await expect(page.locator("#nutritionProductUseMeal")).toHaveValue("");
  await page.locator("#nutritionProductUseAdd").click();
  await expect(page.locator("#nutritionProductStatus")).toContainText("als Snack erfasst");
  await page.goto("/#nutrition/diary");
  await expect(page.locator("#nutritionEntries .nutrition-card").filter({ hasText: "Snack" }).filter({ hasText: productName })).toHaveCount(1);
  await page.goto("/#nutrition/products");
  await page.reload();
  await openProductSection(page, "all");
  await card.getByRole("button", { name: /Als Favorit markieren/ }).click();
  await expect(card.getByRole("button", { name: /Favorit entfernen/ })).toHaveAttribute("aria-pressed", "true");
  const favorites = await openProductSection(page, "favorites");
  await expect(favorites.filter({ hasText: productName })).toHaveCount(1);

  await card.getByRole("button", { name: "Löschen" }).click();
  await expect(page.locator("#confirmationDialog")).toBeVisible();
  await page.locator("#confirmationDialogAccept").click();
  await expect(card).toHaveCount(0);
  await expect(favorites.filter({ hasText: productName })).toHaveCount(0);
});

test("@responsive the product list has sections, markers and the same four actions for own and database products", async ({ page }) => {
  const nutrients = { kcal: 46, carbs_g: 6.7, protein_g: 1, fat_g: 1.5, sugar_g: 4, fiber_g: 0, salt_g: 0.1 };
  const base = { basis_amount: 100, basis_unit: "g", status: "active", filled_fields: {}, favorite: 0, ...nutrients };
  const products = [
    { ...base, id: "yazio:0a1b2c3d-0000-4000-8000-000000000001", name: "Apfelmus", brand: "", barcode: "4000000000031", origin: "yazio", source: "yazio", fetched_at: "2026-09-30", favorite: 1 },
    { ...base, id: "off:4006381333931", name: "Haferdrink", brand: "Beispiel", barcode: "4006381333931", origin: "open_food_facts", source: "open_food_facts", fetched_at: "2026-10-01", sugar_g: null, salt_g: null },
    { ...base, id: "own-musli", name: "Müsli", brand: "Fixture", barcode: null, origin: "own", source: "manual", fetched_at: null, sugar_g: null, salt_g: null },
    { ...base, id: "own-whey", name: "Whey", brand: "Fixture", barcode: "4000000000017", origin: "own", source: "manual", fetched_at: null },
  ];
  const requests = { listed: [], favorite: [], put: [], refresh: [], forget: [] };
  const withMissing = (product) => ({ ...product, missing_fields: ["kcal", "carbs_g", "protein_g", "fat_g", "sugar_g", "fiber_g", "salt_g"].filter((key) => product[key] == null) });
  await page.route("**/api/nutrition/products**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const find = (id) => products.find((product) => product.id === id);
    if (request.method() === "GET") {
      const term = (url.searchParams.get("q") || "").toLowerCase();
      requests.listed.push(url.searchParams.get("scope") + ":" + term);
      return route.fulfill({ json: { ok: true, products: products.filter((product) => !term || [product.name, product.brand, product.barcode].join(" ").toLowerCase().includes(term)).map(withMissing) } });
    }
    const body = request.postDataJSON();
    if (url.pathname.endsWith("/favorite")) { requests.favorite.push(body); find(body.id).favorite = body.favorite ? 1 : 0; return route.fulfill({ json: { ok: true, product: find(body.id) } }); }
    if (url.pathname.endsWith("/database/refresh")) {
      requests.refresh.push(body);
      return route.fulfill({ status: 400, json: { ok: false, error: "Zum Aktualisieren braucht das Produkt eine EAN.", reason: "nutrition_product_barcode_missing" } });
    }
    if (url.pathname.endsWith("/database/delete")) { requests.forget.push(body); products.splice(products.indexOf(find(body.id)), 1); return route.fulfill({ json: { ok: true, id: body.id, status: "removed" } }); }
    if (request.method() === "PUT") { requests.put.push(body); Object.assign(find(body.id), body); return route.fulfill({ json: { ok: true, product: find(body.id) } }); }
    return route.continue();
  });
  await page.goto("/#nutrition/products");
  await expect(productSection(page, "all")).toBeAttached();

  // Both sections are collapsed and count their entries and their incomplete ones.
  const favoritesSummary = productSection(page, "favorites").locator("summary");
  const allSummary = productSection(page, "all").locator("summary");
  await expect(favoritesSummary).toHaveText("Favoriten (1)");
  await expect(allSummary).toHaveText("Alle Produkte (4) ⚠ 2");
  await expect(allSummary.getByRole("img", { name: "2 unvollständig" })).toBeVisible();
  await expect(favoritesSummary.getByRole("img")).toHaveCount(0);
  await expect(productSection(page, "favorites")).not.toHaveAttribute("open", "");
  await expect(productSection(page, "all")).not.toHaveAttribute("open", "");
  await expect(page.locator("#nutritionDatabase")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Datenbank" })).toHaveCount(0);

  // One list by name; each card names its origin and what it lacks.
  const cards = await openProductSection(page, "all");
  await expect(cards).toHaveCount(4);
  await expect(cards.locator("h3")).toHaveText(["Apfelmus", "Beispiel · Haferdrink", "Fixture · Müsli", "Fixture · Whey"]);
  const oat = cards.filter({ hasText: "Haferdrink" });
  await expect(oat).toContainText("Datenbank · Stand 01.10.2026");
  await expect(oat).toContainText("EAN 4006381333931 · Basis: 100 g");
  await expect(oat.getByRole("img", { name: "Unvollständig, es fehlen: Zucker, Salz" })).toHaveText("⚠ fehlt: Zucker, Salz");
  await expect(cards.filter({ hasText: "Whey" })).toContainText("eigen");
  await expect(cards.filter({ hasText: "Whey" }).getByRole("img")).toHaveCount(0);
  for (const name of ["Verwenden", "Bearbeiten", "Aktualisieren", "Löschen"]) await expect(cards.getByRole("button", { name })).toHaveCount(4);
  await expect(cards.getByRole("button", { name: /Favorit/ })).toHaveCount(4);
  await expect(page.getByRole("button", { name: "Lokal speichern" })).toHaveCount(0);

  // A database entry can be marked as a favorite.
  await oat.getByRole("button", { name: /Als Favorit markieren/ }).click();
  await expect(favoritesSummary).toHaveText("Favoriten (2) ⚠ 1");
  expect(requests.favorite).toEqual([{ id: "off:4006381333931", favorite: true }]);

  // Its editor shows name, brand, EAN and basis read only and sends only nutrient values.
  await oat.getByRole("button", { name: "Bearbeiten" }).click();
  const editor = page.locator("#nutritionExtraction");
  await expect(editor).toBeVisible();
  for (const name of ["name", "brand", "barcode", "basis_amount", "basis_unit"]) await expect(editor.locator(`[name="${name}"]`)).toBeDisabled();
  await expect(editor.locator('[name="name"]')).toHaveValue("Haferdrink");
  await editor.locator('[name="sugar_g"]').fill("3.5");
  await editor.locator('[name="salt_g"]').fill("0.1");
  await editor.getByRole("button", { name: "Nährwerte speichern" }).click();
  await expect(page.locator("#nutritionProductStatus")).toContainText("Nährwerte von „Haferdrink“ gespeichert.");
  expect(requests.put).toEqual([{ id: "off:4006381333931", kcal: 46, carbs_g: 6.7, protein_g: 1, fat_g: 1.5, sugar_g: 3.5, fiber_g: 0, salt_g: 0.1, confirmed: true }]);
  await expect(allSummary).toHaveText("Alle Produkte (4) ⚠ 1");
  await expect(oat.getByRole("img")).toHaveCount(0);

  // An own product without an EAN cannot be re-checked; the editor takes the EAN.
  const musli = cards.filter({ hasText: "Müsli" });
  await musli.getByRole("button", { name: "Aktualisieren" }).click();
  await expect(page.locator("#nutritionProductStatus")).toHaveText("Für Aktualisieren wird eine EAN gebraucht. Unter Bearbeiten eintragen.");
  expect(requests.refresh).toEqual([{ id: "own-musli" }]);
  await musli.getByRole("button", { name: "Bearbeiten" }).click();
  await expect(editor.locator('[name="barcode"]')).toBeEnabled();
  await expect(editor.locator('[name="name"]')).toBeEnabled();
  await editor.getByRole("button", { name: "Abbrechen" }).click();

  // Deleting a database entry asks first and removes it from the database.
  await oat.getByRole("button", { name: "Löschen" }).click();
  await expect(page.locator("#confirmationDialog")).toContainText("Eintrag „Haferdrink“ aus der Datenbank entfernen?");
  await page.locator("#confirmationDialogAccept").click();
  await expect(cards).toHaveCount(3);
  expect(requests.forget).toEqual([{ id: "off:4006381333931", confirmed: true }]);
  await expect(page.locator("#nutritionProductStatus")).toContainText("aus der Datenbank entfernt");

  // A search covers all products and opens the sections with hits.
  await allSummary.click();
  await expect(productSection(page, "all")).not.toHaveAttribute("open", "");
  await page.locator("#nutritionProductQuery").fill("4000000000017");
  await page.locator("#nutritionProductSearch").getByRole("button", { name: "Suchen" }).click();
  await expect(cards).toHaveCount(1);
  await expect(productSection(page, "all")).toHaveAttribute("open", "");
  await expect(productSection(page, "favorites")).not.toHaveAttribute("open", "");
  expect(requests.listed.at(-1)).toBe("all:4000000000017");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
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
  const chooser = page.waitForEvent("filechooser");
  await page.locator("#nutritionLabelButton").click();
  await (await chooser).setFiles({ name: "label.jpg", mimeType: "image/jpg", buffer: onePixel });
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
  await expect(page.locator("#nutritionBarcodeDialog #nutritionBarcodeVideo")).toBeAttached();
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
        product: { id: "off:4006381333931", name: "Bio Haferdrink", brands: "Beispiel", per_100: { kcal: 46, carbs_g: 6.7, protein_g: 1, fat_g: 1.5, sugar_g: 4, fiber_g: 0, salt_g: 0.03 }, basis_amount: 100, basis_unit: "ml", source: "open_food_facts", source_url: "https://world.openfoodfacts.org/product/4006381333931" },
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
  await expect(editor.locator('[name="sugar_g"]')).toHaveValue("4");
  await expect(editor.locator('[name="fiber_g"]')).toHaveValue("0");
  await expect(editor.locator('[name="salt_g"]')).toHaveValue("0.03");

  await editor.getByRole("button", { name: "Produkt lokal speichern" }).click();
  await expect.poll(() => savedPayload?.name).toBe("Bio Haferdrink");
  expect(savedPayload.source).toBe("open_food_facts");
  expect(savedPayload.external_id).toBe("off:4006381333931");
  expect(savedPayload.barcode).toBe("4006381333931");
  expect(savedPayload.sugar_g).toBe(4);
  expect(savedPayload.fiber_g).toBe(0);
  expect(savedPayload.salt_g).toBe(0.03);
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
  await expect(card).not.toContainText("Zusammengesetztes Essen");
  await expect(card).not.toContainText("Herkunft je Zutat");
  await expect(card).not.toContainText("\u00b7 Lokal");
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
  // The Coach receipt undoes the logged meal directly.
  await page.goto("/#coach");
  const receipt = page.locator("#messages .message.assistant .message-changes").last();
  await expect(receipt).toContainText("Ernährungseintrag");
  const undoButton = receipt.getByRole("button", { name: "Rückgängig" });
  await expect(undoButton).toBeVisible();
  // A startup load that began before the undo would redraw the receipt from older messages.
  await waitForSettledState(page);
  await undoButton.click();
  const [undo] = await Promise.all([
    page.waitForResponse((response) => response.url().includes("/api/change-history/undo-turn")),
    page.locator("#confirmationDialogAccept").click(),
  ]);
  expect(undo.status(), await undo.text()).toBe(200);
  // The HTTP answer only starts the update; the receipt itself shows the undone state.
  await expect(receipt).toContainText("Zurückgenommen");
  await expect(receipt.getByRole("button", { name: "Rückgängig" })).toHaveCount(0);
  await expect.poll(() => page.evaluate(async () => (await api("/api/nutrition/day")).entry_count)).toBe(initialEntries);
});

test.describe("diary failure interception", () => {
  test.use({ serviceWorkers: "block" });

test("@responsive a failed diary load keeps the requested date, shows one error and retries the day", async ({ page }) => {
  let failing = true;
  await page.goto("/#nutrition/diary");
  await expect(page.locator("#nutritionStatus")).not.toContainText("wird geladen");
  await page.evaluate(() => localStorage.removeItem("coach-view-cache"));
  await page.route("**/api/nutrition/day**", (route) => failing ? route.fulfill({ status: 503, json: { error: "Dienst nicht verfügbar" } }) : route.continue());
  await page.locator("#nutritionDate").fill("2026-10-05");
  await page.locator("#nutritionDate").dispatchEvent("change");
  await expect(page.locator("#nutritionStatus")).toContainText("Ernährung konnte nicht geladen werden");
  await expect(page.locator("#nutritionDate")).toHaveValue("2026-10-05");
  await expect(page.locator("#nutritionExpenditure")).toBeHidden();
  await expect(page.locator("#nutritionPanel").getByText("konnte nicht geladen werden")).toHaveCount(1);
  const dayResponse = (date, status) => page.waitForResponse((response) => response.url().includes(`/api/nutrition/day?date=${date}`) && response.status() === status);
  const failedNext = dayResponse("2026-10-06", 503);
  await page.locator("#nutritionNext").click();
  await failedNext;
  await expect(page.locator("#nutritionStatus")).toContainText("Ernährung konnte nicht geladen werden");
  await expect(page.locator("#nutritionDate")).toHaveValue("2026-10-06");
  const failedPrevious = dayResponse("2026-10-05", 503);
  await page.locator("#nutritionPrevious").click();
  await failedPrevious;
  await expect(page.locator("#nutritionStatus")).toContainText("Ernährung konnte nicht geladen werden");
  await expect(page.locator("#nutritionDate")).toHaveValue("2026-10-05");
  failing = false;
  const retried = dayResponse("2026-10-05", 200);
  await page.getByRole("button", { name: "Erneut laden" }).click();
  await retried;
  await expect(page.locator("#nutritionStatus")).toContainText("Noch keine Mahlzeiten erfasst");
  await expect(page.locator("#nutritionStatus")).not.toContainText("wird geladen");
  await expect(page.locator("#nutritionStatus")).not.toContainText("konnte nicht geladen werden");
  await expect(page.locator("#nutritionStatus").getByRole("button")).toHaveCount(0);
  await expect(page.locator("#nutritionDate")).toHaveValue("2026-10-05");
  await expect(page.locator("#nutritionExpenditure")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
});

test("@responsive a stored database entry is refreshed on request and the list is read again", async ({ page }) => {
  let salt = null;
  let listed = 0;
  const refreshes = [];
  await page.route("**/api/nutrition/products**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/database/refresh")) {
      refreshes.push(request.postDataJSON());
      salt = 0.4;
      return route.fulfill({ json: { ok: true, food: { id: "off:4006381333931" } } });
    }
    if (request.method() === "GET" && url.searchParams.get("scope") === "all") {
      listed += 1;
      return route.fulfill({ json: { ok: true, products: [{
        id: "off:4006381333931", name: "Haselnuss Riegel", brand: "Beispiel", barcode: "4006381333931", basis_amount: 100, basis_unit: "g",
        kcal: 540, carbs_g: 50, protein_g: 8, fat_g: 33, sugar_g: 40, fiber_g: 3, salt_g: salt, origin: "open_food_facts", source: "open_food_facts",
        fetched_at: "2026-10-01", favorite: 0, status: "active", filled_fields: {}, missing_fields: salt === null ? ["salt_g"] : [],
      }] } });
    }
    return route.continue();
  });
  await page.goto("/#nutrition/products");
  const cards = await openProductSection(page, "all");
  const card = cards.filter({ hasText: "Haselnuss Riegel" });
  await expect(card).toContainText("fehlt: Salz");
  await card.getByRole("button", { name: "Aktualisieren" }).click();
  await expect(page.locator("#nutritionProductStatus")).toContainText("„Haselnuss Riegel“ aktualisiert.");
  expect(refreshes).toEqual([{ id: "off:4006381333931" }]);
  // The list is read again after the refresh, so the filled value is shown.
  await expect.poll(() => listed).toBeGreaterThan(1);
  await expect(card).not.toContainText("fehlt:");
});
