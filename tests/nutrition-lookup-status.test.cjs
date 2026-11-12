const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

function harness(apiImpl) {
  const elements = {
    "#nutritionProductStatus": { textContent: "" },
    "#nutritionBarcodeStatus": { textContent: "" },
    "#nutritionBarcodeDialog": { close() {} },
  };
  const rendered = [];
  const databaseLoads = [];
  const context = extractFunctions("nutrition.js", ["nutritionProductLoadSequence", "nutritionLookupResultShown", "isCurrentNutritionProductLoad", "prepareNutritionProductLookup", "showNutritionProductLoadError", "loadNutritionProducts", "lookupNutritionProduct"], {
    state: { sessionGeneration: 1 },
    document: { querySelector: (selector) => elements[selector] || null },
    api: apiImpl,
    renderNutritionProducts: (products) => rendered.push(products),
    saveNutritionProduct: async () => {},
    loadNutritionDatabase: async (query) => { databaseLoads.push(query); },
    normalizeNutritionProduct: (product) => product,
  });
  return { context, elements, rendered, databaseLoads };
}

test("a product search also lists the stored database entries for the same query", async () => {
  const { context, databaseLoads } = harness(async () => ({ products: [] }));
  await context.loadNutritionProducts("hafer");
  assert.deepEqual(databaseLoads, ["hafer"]);
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
  assert.equal(elements["#nutritionProductStatus"].textContent, "Keine lokalen Produkte gefunden.");
  await context.loadNutritionProducts("", { background: true });
  assert.equal(elements["#nutritionProductStatus"].textContent, "Keine lokalen Produkte gefunden.");
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
