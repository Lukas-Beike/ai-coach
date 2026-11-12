const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { extractFunctions, FakeElement, textOf } = require("./frontend-harness.cjs");

function harness(apiImpl) {
  const elements = {
    "#nutritionProductStatus": { textContent: "" },
    "#nutritionBarcodeStatus": { textContent: "" },
    "#nutritionBarcodeDialog": { close() {} },
  };
  const rendered = [];
  const context = extractFunctions("nutrition.js", ["nutritionProductLoadSequence", "nutritionLookupResultShown", "isCurrentNutritionProductLoad", "prepareNutritionProductLookup", "showNutritionProductLoadError", "loadNutritionProducts", "lookupNutritionProduct"], {
    state: { sessionGeneration: 1 },
    document: { querySelector: (selector) => elements[selector] || null },
    api: apiImpl,
    renderNutritionProducts: (products, options) => rendered.push([products, options]),
    saveNutritionProduct: async () => {},
    normalizeNutritionProduct: (product) => product,
  });
  return { context, elements, rendered };
}

test("the product list is one request for all products, and a search is passed on to the sections", async () => {
  const urls = [];
  const { context, rendered } = harness(async (url) => { urls.push(url); return { products: [{ id: "p1" }] }; });
  await context.loadNutritionProducts("");
  await context.loadNutritionProducts("hafer & co");
  assert.deepEqual(urls, ["/api/nutrition/products?scope=all", "/api/nutrition/products?scope=all&q=hafer%20%26%20co"]);
  assert.deepEqual(rendered.map(([, options]) => options.search), ["", "hafer & co"]);
});

const LOCAL_LOOKUP = { ok: true, source: "manual", local: true, product: { id: "p1", name: "Haferdrink" } };

test("a background state render does not clobber a fresh lookup result", async () => {
  const { context, elements, rendered } = harness(async (url) => (url.includes("/lookup") ? LOCAL_LOOKUP : { products: [] }));
  await context.lookupNutritionProduct("4006381333931");
  assert.equal(elements["#nutritionProductStatus"].textContent, "Lokales Produkt gefunden.");
  await context.loadNutritionProducts("", { background: true });
  assert.equal(elements["#nutritionProductStatus"].textContent, "Lokales Produkt gefunden.");
  assert.equal(rendered.length, 1);
});

test("a product reload started before the lookup cannot overwrite its result", async () => {
  let releaseList;
  const listGate = new Promise((resolve) => { releaseList = resolve; });
  const { context, elements, rendered } = harness(async (url) => {
    if (url.includes("/lookup")) return LOCAL_LOOKUP;
    await listGate;
    return { products: [] };
  });
  const pending = context.loadNutritionProducts("", { background: true });
  await context.lookupNutritionProduct("4006381333931");
  releaseList();
  await pending;
  assert.equal(elements["#nutritionProductStatus"].textContent, "Lokales Produkt gefunden.");
  assert.equal(rendered.length, 1);
});

test("an explicit product search still replaces the lookup result", async () => {
  const { context, elements } = harness(async (url) => (url.includes("/lookup") ? LOCAL_LOOKUP : { products: [] }));
  await context.lookupNutritionProduct("4006381333931");
  await context.loadNutritionProducts("hafer");
  assert.equal(elements["#nutritionProductStatus"].textContent, "Keine Produkte gefunden.");
  await context.loadNutritionProducts("", { background: true });
  assert.equal(elements["#nutritionProductStatus"].textContent, "Keine Produkte gefunden.");
});

test("online nutrients fill the product editor without replacing zero or local values", () => {
  const context = extractFunctions("nutrition.js", ["normalizeNutritionProduct"], { nutritionDatabaseSource: (source) => source });
  const result = context.normalizeNutritionProduct({
    source: "yazio", sugar_g: 0, per_100: { sugar_g: 5, fiber_g: 2, salt_g: null },
  });
  assert.equal(result.sugar_g, 0);
  assert.equal(result.fiber_g, 2);
  assert.equal(result.salt_g, null);
});

test("product editor follows the barcode result before the product lists", () => {
  const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
  assert.ok(html.indexOf('id="nutritionLookupResult"') < html.indexOf('id="nutritionExtraction"'));
  assert.ok(html.indexOf('id="nutritionExtraction"') < html.indexOf('id="nutritionProducts"'));
});

// The product page: one merged list in two sections (#2267).
const LIST_FUNCTIONS = ["NUTRITION_FIELD_NAMES", "NUTRITION_SOURCE_NAMES", "NUTRITION_PRODUCT_SECTIONS", "nutritionProductSectionsOpen", "nutritionProductSearchShown", "nutritionProductSectionsBeforeSearch", "nutritionIsDatabaseProduct", "nutritionMissingFields", "nutritionProductDate", "nutritionOriginText", "nutritionIncompleteMark", "nutritionProductSection", "nutritionProductCard", "renderNutritionProducts", "appendNutritionProductActions", "nutritionFavoriteButton", "normalizeNutritionProduct", "nutritionDatabaseSource"];
const OWN = { id: "own-1", name: "Whey", brand: "Fixture", barcode: "4000000000017", basis_amount: 100, basis_unit: "g", origin: "own", fetched_at: null, favorite: 1, kcal: 380, carbs_g: 5, protein_g: 72, fat_g: 6, sugar_g: 2, fiber_g: 1, salt_g: 0.1, missing_fields: [] };
const FOOD = { id: "off:4006381333931", name: "Haferdrink", brand: "Beispiel", barcode: "4006381333931", basis_amount: 100, basis_unit: "ml", origin: "open_food_facts", source: "open_food_facts", fetched_at: "2026-10-01T08:00:00+00:00", favorite: 0, kcal: 46, carbs_g: 6.7, protein_g: 1, fat_g: 1.5, sugar_g: null, fiber_g: 0, salt_g: null, missing_fields: ["sugar_g", "salt_g"] };

const descendants = (node) => node.children.filter((child) => typeof child !== "string").flatMap((child) => [child, ...descendants(child)]);
const withClass = (node, name) => descendants(node).filter((child) => child.className.split(" ").includes(name));

function listContext() {
  const targets = { "#nutritionProducts": new FakeElement(), "#nutritionLookupResult": new FakeElement() };
  const document = { createElement: (tag) => new FakeElement(tag), querySelector: (selector) => targets[selector] || null };
  const context = extractFunctions("nutrition.js", LIST_FUNCTIONS, {
    document,
    api: async () => ({}),
    useNutritionProduct() {}, saveNutritionProduct() {}, refreshNutritionProduct() {}, deleteNutritionProduct() {}, reloadNutritionProducts() {},
    showNutritionProductError() {},
  });
  return { context, target: targets["#nutritionProducts"], lookup: targets["#nutritionLookupResult"] };
}

test("both sections start collapsed and name their total and their incomplete entries", () => {
  const { context, target } = listContext();
  context.renderNutritionProducts([OWN, FOOD]);
  const [favorites, all] = target.children;
  assert.deepEqual([favorites, all].map((section) => section.open), [false, false]);
  assert.deepEqual([favorites, all].map((section) => textOf(section.children[0])), ["Favoriten (1)", "Alle Produkte (2) ⚠ 1"]);
  assert.equal(withClass(all.children[0], "nutrition-incomplete")[0].attributes["aria-label"], "1 unvollständig");
  assert.equal(withClass(favorites.children[0], "nutrition-incomplete").length, 0);
  assert.equal(all.children[1].children.length, 2);
  assert.equal(favorites.children[1].children.length, 1);
});

test("an opened section stays open on the next render until the page is left", () => {
  const { context, target } = listContext();
  context.renderNutritionProducts([OWN, FOOD]);
  target.children[1].open = true;
  target.children[1].listeners.toggle();
  context.renderNutritionProducts([OWN, FOOD]);
  assert.deepEqual(target.children.map((section) => section.open), [false, true]);
});

test("a new search opens sections with hits once, keeps toggles, and ends as before", () => {
  const { context, target } = listContext();
  context.renderNutritionProducts([FOOD], { search: "riegel" });
  assert.deepEqual(target.children.map((section) => section.open), [false, true]);
  // The athlete closes a section; a re-render of the same search keeps it closed.
  target.children[1].open = false;
  target.children[1].listeners.toggle();
  context.renderNutritionProducts([FOOD], { search: "riegel" });
  assert.deepEqual(target.children.map((section) => section.open), [false, false]);
  // Ending the search restores what was open before it.
  context.renderNutritionProducts([FOOD], { search: "riegel bar" });
  context.renderNutritionProducts([FOOD]);
  assert.deepEqual(target.children.map((section) => section.open), [false, false]);
});

test("every card shows its origin, its missing fields and the same actions and star", () => {
  const { context, target } = listContext();
  context.renderNutritionProducts([OWN, FOOD]);
  const [own, food] = target.children[1].children[1].children;
  // An own product names where its values came from.
  assert.match(textOf(withClass(own, "nutrition-origin")[0]), /^eigen( · .+)?$/);
  assert.equal(textOf(withClass(food, "nutrition-origin")[0]), "Datenbank · Stand 01.10.2026");
  assert.equal(withClass(own, "nutrition-incomplete").length, 0);
  const missing = withClass(food, "nutrition-incomplete")[0];
  assert.equal(textOf(missing), "⚠ fehlt: Zucker, Salz");
  assert.equal(missing.attributes["aria-label"], "Unvollständig, es fehlen: Zucker, Salz");
  assert.match(textOf(food), /EAN 4006381333931 · Basis: 100 ml/);
  for (const card of [own, food]) {
    assert.deepEqual(withClass(card, "nutrition-actions")[0].children.map(textOf), ["Verwenden", "Bearbeiten", "Aktualisieren", "Löschen"]);
    assert.equal(withClass(card, "nutrition-favorite").length, 1);
  }
  assert.equal(withClass(food, "nutrition-favorite")[0].attributes["aria-pressed"], "false");
});

test("a product without a known unit cannot be used, and its date is the local day", () => {
  const { context, target } = listContext();
  // 23:30 UTC on 1 October is already 2 October in Berlin.
  const late = { ...FOOD, basis_unit: null, fetched_at: "2026-10-01T23:30:00+00:00" };
  context.renderNutritionProducts([late]);
  const [card] = target.children[1].children[1].children;
  const [use] = withClass(card, "nutrition-actions")[0].children;
  assert.equal(use.disabled, true);
  assert.match(textOf(card), /Bezugsmenge unbekannt/);
  const expected = new Date(late.fetched_at).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
  assert.equal(textOf(withClass(card, "nutrition-origin")[0]), `Datenbank · Stand ${expected}`);
});

test("a live lookup hit is not a stored product: it only offers saving it locally", () => {
  const { context, lookup } = listContext();
  context.renderNutritionProducts([{ id: "off:4006381333931", name: "Bio Haferdrink", brands: "Beispiel", source: "open_food_facts", local: false, per_100: { kcal: 46 } }], { local: false, targetId: "#nutritionLookupResult" });
  const [card] = lookup.children;
  assert.deepEqual(card.children.filter((child) => child.tag === "button").map(textOf), ["Lokal speichern"]);
  assert.equal(withClass(card, "nutrition-favorite").length, 0);
  assert.equal(textOf(withClass(card, "nutrition-origin")[0]), "Datenbank");
});

test("a stored database entry keeps its id, a live hit loses it", () => {
  const { context } = listContext();
  assert.equal(context.normalizeNutritionProduct(FOOD).id, "off:4006381333931");
  const live = context.normalizeNutritionProduct({ id: "off:4006381333931", source: "open_food_facts", name: "Haferdrink" });
  assert.equal(live.id, undefined);
  assert.equal(live.external_id, "off:4006381333931");
});

// The actions behind the four buttons.
function actionContext(responses) {
  const calls = [];
  const status = new FakeElement();
  const context = extractFunctions("nutrition.js", ["nutritionIsDatabaseProduct", "reloadNutritionProducts", "showNutritionProductError", "refreshNutritionProduct", "deleteNutritionProduct"], {
    document: { querySelector: () => status },
    api: async (url, options) => { calls.push([url, JSON.parse(options.body)]); const response = responses[url]; if (response instanceof Error) throw response; return response || {}; },
    requestConfirmation: async (question) => { calls.push(["confirm", question]); return true; },
    showNutritionReceipt: (_status, message) => { status.textContent = message; },
    loadNutritionProducts: async () => {},
    state: { sessionGeneration: 1 },
  });
  return { context, calls, status };
}

test("deleting a database entry removes it from the database after its own confirmation", async () => {
  const { context, calls, status } = actionContext({});
  await context.deleteNutritionProduct({ id: "off:1", name: "Haferdrink", origin: "open_food_facts" });
  assert.deepEqual(calls, [["confirm", "Eintrag „Haferdrink“ aus der Datenbank entfernen? Eigene Produkte bleiben erhalten."], ["/api/nutrition/products/database/delete", { id: "off:1", confirmed: true }]]);
  assert.equal(status.textContent, "Eintrag „Haferdrink“ aus der Datenbank entfernt.");
});

test("deleting an own product archives it after confirmation", async () => {
  const { context, calls } = actionContext({});
  await context.deleteNutritionProduct({ id: "own-1", name: "Whey", origin: "own" });
  assert.deepEqual(calls.map(([target]) => target), ["confirm", "/api/nutrition/products/archive"]);
});

test("re-checking an own product without an EAN names the EAN and the editor", async () => {
  const error = Object.assign(new Error("server text"), { reason: "nutrition_product_barcode_missing" });
  const { context, status } = actionContext({ "/api/nutrition/products/database/refresh": error });
  const button = new FakeElement("button");
  await context.refreshNutritionProduct({ id: "own-1", name: "Whey", origin: "own" }, button);
  assert.equal(status.textContent, "Für Aktualisieren wird eine EAN gebraucht. Unter Bearbeiten eintragen.");
  assert.equal(button.disabled, false);
});

test("a logout while the list reloads leaves no receipt of a re-check or delete", async () => {
  for (const [action, product] of [["refreshNutritionProduct", { id: "off:1", name: "Haferdrink", origin: "open_food_facts" }], ["deleteNutritionProduct", { id: "own-1", name: "Whey", origin: "own" }]]) {
    const { context, status } = actionContext({});
    context.loadNutritionProducts = async () => { context.state.sessionGeneration += 1; };
    await context[action](product, new FakeElement("button"));
    assert.equal(status.textContent, "", action);
  }
});

test("a re-check shows the outcome the server reports", async () => {
  const { context, status } = actionContext({ "/api/nutrition/products/database/refresh": { ok: true, notice: "Nichts zu ergänzen." } });
  await context.refreshNutritionProduct({ id: "off:1", name: "Haferdrink", origin: "open_food_facts" }, new FakeElement("button"));
  assert.equal(status.textContent, "„Haferdrink“ aktualisiert. Nichts zu ergänzen.");
});
