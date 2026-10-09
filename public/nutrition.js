// Read-only nutrition views; every write remains an explicit Coach request.
let nutritionLoadSequence = 0;

const MAX_NUTRITION_IMAGE_EDGE = 1600;
const MAX_NUTRITION_IMAGE_BYTES = 1_200_000;

async function nutritionImageDataUrl(blob, mime) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCodePoint(...bytes.subarray(offset, Math.min(offset + 0x8000, bytes.length)));
  }
  return `data:${mime};base64,${btoa(binary)}`;
}

async function resizeNutritionImage(bitmap, maxEdge, maxBytes) {
  const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) throw new Error("Die Bildverarbeitung ist auf diesem Gerät nicht verfügbar.");
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  let blob;
  for (const quality of [0.84, 0.72, 0.6, 0.48]) {
    blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
    if (blob && blob.size <= maxBytes) break;
  }
  if (!blob || blob.size > maxBytes) throw new Error("Das Foto ließ sich nicht ausreichend verkleinern. Bitte ein kleineres Bild wählen.");
  return { dataUrl: await nutritionImageDataUrl(blob, "image/jpeg"), blob, width: canvas.width, height: canvas.height, mime: "image/jpeg" };
}

async function prepareNutritionImage(file, { maxEdge = MAX_NUTRITION_IMAGE_EDGE, maxBytes = MAX_NUTRITION_IMAGE_BYTES } = {}) {
  if (!file || !/^image\/(png|jpe?g|webp)$/i.test(file.type)) throw new Error("Bitte ein JPEG-, PNG- oder WebP-Bild auswählen.");
  if (!file.size || file.size > 15_000_000) throw new Error("Das Foto darf höchstens 15 MB groß sein.");
  const normalizedMime = String(file.type || "").toLowerCase() === "image/jpg" ? "image/jpeg" : String(file.type || "").toLowerCase();
  let bitmap;
  let objectUrl;
  try {
    if (typeof createImageBitmap === "function") bitmap = await createImageBitmap(file, { imageOrientation: "from-image", resizeWidth: maxEdge, resizeQuality: "high" });
    else {
      objectUrl = URL.createObjectURL(file);
      bitmap = await new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error("Das Foto konnte nicht dekodiert werden."));
        image.src = objectUrl;
      });
    }
    if (bitmap.width <= maxEdge && bitmap.height <= maxEdge && file.size <= maxBytes) {
      return { dataUrl: await nutritionImageDataUrl(file, normalizedMime), blob: file, width: bitmap.width, height: bitmap.height, mime: normalizedMime };
    }
    return await resizeNutritionImage(bitmap, maxEdge, maxBytes);
  } finally {
    bitmap?.close?.();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
}

function renderNutritionSegments(route) {
  const meals = route === "nutrition/meals";
  const products = route === "nutrition/products";
  document.querySelector("#nutritionDiary").hidden = meals || products;
  document.querySelector("#nutritionMeals").hidden = !meals;
  document.querySelector("#nutritionProductsPanel").hidden = !products;
  document.querySelectorAll("[data-nutrition-segment]").forEach((link) => {
    let activeSegment = "diary";
    if (meals) activeSegment = "meals";
    if (products) activeSegment = "products";
    const active = link.dataset.nutritionSegment === activeSegment;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function nutritionNumber(value) {
  if (value == null || value === "") return "–";
  const number = Number(value);
  return Number.isFinite(number) ? String(Math.round(number * 10) / 10) : String(value);
}

function nutritionComponentSource(basis) {
  const kind = basis?.kind;
  if (kind === "local_product" || kind === "product") {
    const product = basis.product || basis;
    const source = product.source === "packaging_label" ? "Verpackungsangabe" : product.source;
    const label = product.product_name || product.name || "Gespeichertes Produkt";
    return ["Gespeichertes Produkt: " + label, source].filter(Boolean).join(" · ");
  }
  if (kind === "database") {
    const food = basis.food || basis;
    return [food.source || "Datenbank", food.name].filter(Boolean).join(": ");
  }
  if (kind === "packaging_label") return "Verpackungsangabe";
  if (kind === "manual") return "Manuelle Angabe";
  if (kind === "estimate") return "Schätzung";
  return "Quelle unbekannt";
}

function nutritionBasisLabel(basis, item, sourceLabel) {
  if (basis?.kind === "composite") return "Zusammengesetztes Essen · Herkunft je Zutat";
  if (basis?.kind === "database") {
    return "Datenbankberechnung · " + basis.ingredients.map((food) => `${food.source}: ${food.name}, ${food.amount} ${food.unit} (Basis 100 ${food.basis_unit})`).join("; ");
  }
  if (basis?.kind === "product" || basis?.kind === "local_product") {
    const product = basis.product || basis;
    const name = product.product_name || product.name || "Produkt";
    const source = product.source ? ` (${product.source})` : "";
    const amount = basis.amount != null ? ` · ${basis.amount} ${basis.unit || "g"}` : "";
    return `Lokales Produkt · ${name}${source}${amount}`;
  }
  if (basis?.kind === "manual_correction") return "Manuell korrigierte Nährwerte";
  if (basis?.kind === "packaging_label") return "Verpackungsangabe";
  return sourceLabel;
}

function nutritionComponentDetails(item) {
  const components = item.nutrition_basis?.kind === "composite" ? item.nutrition_basis.components : [];
  if (!Array.isArray(components) || !components.length) return null;
  const details = document.createElement("details");
  details.className = "nutrition-components";
  const summary = document.createElement("summary");
  summary.textContent = `Zutaten anzeigen (${components.length})`;
  const list = document.createElement("ul");
  list.className = "nutrition-component-list";
  for (const component of components) {
    const row = document.createElement("li");
    const name = document.createElement("strong"); name.textContent = component.name || "Unbenannte Zutat";
    const amount = document.createElement("span"); amount.textContent = ` · ${component.amount ?? "–"} ${component.unit || ""}`.trim();
    const nutrients = document.createElement("span"); nutrients.textContent = ` · ${nutritionNumber(component.kcal)} kcal · KH ${nutritionNumber(component.carbs_g)} g · Protein ${nutritionNumber(component.protein_g)} g · Fett ${nutritionNumber(component.fat_g)} g`;
    const source = document.createElement("small"); source.textContent = nutritionComponentSource(component.nutrition_basis);
    row.append(name, amount, nutrients, source); list.append(row);
  }
  details.append(summary, list); return details;
}

function nutritionCard(item, template) {
  const card = document.createElement("article");
  card.className = "nutrition-card";
  const title = document.createElement("h3");
  const mealLabels = { breakfast: "Frühstück", lunch: "Mittagessen", dinner: "Abendessen", snack: "Snack" };
  const mealLabel = mealLabels[item.meal_type] || "Mahlzeit";
  const mealTime = String(item.logged_at).split("T")[1]?.slice(0, 5) || "";
  title.textContent = template ? item.name : `${mealTime} · ${mealLabel}`;
  const description = document.createElement("p");
  description.textContent = item.description;
  const values = document.createElement("p");
  values.textContent = `${nutritionNumber(item.kcal)} kcal · KH ${nutritionNumber(item.carbs_g)} g · Protein ${nutritionNumber(item.protein_g)} g · Fett ${nutritionNumber(item.fat_g)} g${template ? " / Portion" : ""}`;
  const source = document.createElement("small");
  const sourceLabels = { coach: "Coach-Schätzung", photo: "Foto-Schätzung", voice: "Sprach-Schätzung", manual: "Manuelle Angabe" };
  const sourceLabel = sourceLabels[item.source] || "Erfasst";
  const syncLabel = item.sync_state === "synced" ? " · Synchronisiert" : " · Lokal";
  const basisLabel = nutritionBasisLabel(item.nutrition_basis, { template, syncLabel }, sourceLabel);
  source.textContent = basisLabel + (template ? "" : syncLabel);
  card.append(title, description, values, source);
  if (!template) {
    const details = nutritionComponentDetails(item);
    if (details) card.append(details);
  }
  return card;
}

function nutritionExpenditureSection() {
  let section = document.querySelector("#nutritionExpenditure");
  if (section) return section;
  section = document.createElement("section");
  section.id = "nutritionExpenditure";
  section.className = "nutrition-tools";
  section.setAttribute("aria-label", "Garmin-Energieverbrauch");
  const heading = document.createElement("h3");
  heading.textContent = "Energieverbrauch";
  const status = document.createElement("output");
  status.id = "nutritionExpenditureStatus";
  status.className = "tab-sync-detail";
  status.setAttribute("aria-live", "polite");
  const totals = document.createElement("div");
  totals.id = "nutritionExpenditureTotals";
  totals.className = "nutrition-totals";
  const date = document.createElement("p");
  date.id = "nutritionExpenditureDate";
  date.className = "fine-print";
  section.append(heading, status, totals, date);
  document.querySelector("#nutritionTotals").insertAdjacentElement("afterend", section);
  return section;
}

function nutritionExpenditureDate(value) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Datum unbekannt";
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return "Datum unbekannt";
  return new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" }).format(parsed);
}

function nutritionExpenditureTimestamp(value) {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? String(value)
    : new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(parsed);
}

function clearNutritionExpenditure(message = "Garmin-Tagesverbrauch wird geladen…") {
  const section = nutritionExpenditureSection();
  section.querySelector("#nutritionExpenditureStatus").textContent = message;
  section.querySelector("#nutritionExpenditureTotals").replaceChildren();
  section.querySelector("#nutritionExpenditureDate").textContent = "";
}

function renderNutritionExpenditure(expenditure, selectedDate) {
  const section = nutritionExpenditureSection();
  const status = section.querySelector("#nutritionExpenditureStatus");
  const totals = section.querySelector("#nutritionExpenditureTotals");
  const date = section.querySelector("#nutritionExpenditureDate");
  const measured = expenditure?.status === "measured"
    || [expenditure?.total_kcal, expenditure?.active_kcal, expenditure?.resting_kcal].some((value) => value != null && Number.isFinite(Number(value)));
  const freshnessLabels = { current: "Aktuell", stale: "Veraltet", delayed: "Verzögert" };
  const freshness = freshnessLabels[expenditure?.freshness] || "Aktualität unbekannt";
  const provisionalLabel = expenditure?.provisional ? " · Vorläufig, da der Tag noch läuft" : "";
  status.textContent = "Für diesen Tag liegen keine Garmin-Verbrauchsdaten vor.";
  if (measured) status.textContent = [expenditure.source || "Garmin Connect", freshness].join(" · ") + provisionalLabel;

  const formatKcal = (rawValue) => {
    const value = rawValue == null || rawValue === "" ? null : Number(rawValue);
    return value != null && Number.isFinite(value)
      ? `${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 }).format(value)} kcal`
      : "Nicht verfügbar";
  };
  const totalTile = document.createElement("div");
  totalTile.className = "nutrition-total";
  totalTile.style.gridColumn = "1 / -1";
  const totalValue = document.createElement("strong");
  totalValue.textContent = formatKcal(expenditure?.total_kcal);
  const totalCaption = document.createElement("span");
  totalCaption.textContent = "Gesamtverbrauch";
  totalTile.append(totalValue, totalCaption);

  const componentDetails = document.createElement("details");
  componentDetails.style.gridColumn = "1 / -1";
  const componentSummary = document.createElement("summary");
  componentSummary.textContent = "Aktiv- und Ruheenergie anzeigen";
  const componentText = document.createElement("p");
  componentText.textContent = `Aktiv: ${formatKcal(expenditure?.active_kcal)} · Ruhe: ${formatKcal(expenditure?.resting_kcal)}`;
  componentDetails.append(componentSummary, componentText);
  totals.replaceChildren(totalTile, componentDetails);

  const measuredDate = expenditure?.measured_date || expenditure?.date || selectedDate || "";
  const fetchedAt = nutritionExpenditureTimestamp(expenditure?.fetched_at);
  const syncedAt = nutritionExpenditureTimestamp(expenditure?.synced_at);
  const timestamps = [
    fetchedAt ? `Abgerufen: ${fetchedAt}` : "",
    syncedAt ? `Garmin-Sync: ${syncedAt}` : "",
  ].filter(Boolean).join(" · ");
  const dateParts = ["Messdatum: " + nutritionExpenditureDate(measuredDate)];
  if (measured && expenditure.provisional) dateParts.push("Vorläufiger Tageswert");
  if (!measured) dateParts.push("Status: nicht verfügbar");
  if (timestamps) dateParts.push(timestamps);
  date.textContent = dateParts.join(" · ");
}

async function loadNutrition() {
  const sequence = ++nutritionLoadSequence;
  const generation = state.sessionGeneration;
  const dateInput = document.querySelector("#nutritionDate");
  const status = document.querySelector("#nutritionStatus");
  status.textContent = "Ernährung wird geladen…";
  clearNutritionExpenditure();
  document.querySelector("#nutritionEntries").replaceChildren();
  document.querySelector("#nutritionTemplates").replaceChildren();
  document.querySelector("#nutritionTotals").replaceChildren();
  try {
    const dateQuery = dateInput.value ? `?date=${encodeURIComponent(dateInput.value)}` : "";
    const [day, saved] = await Promise.all([
      api(`/api/nutrition/day${dateQuery}`),
      api("/api/nutrition/templates"),
    ]);
    if (sequence !== nutritionLoadSequence || generation !== state.sessionGeneration) return;
    dateInput.value = day.date;
    renderNutritionExpenditure(day.energy_expenditure, day.date);
    status.textContent = day.entry_count ? "" : "Noch keine Mahlzeiten erfasst. Das bedeutet nicht, dass du nichts gegessen hast.";
    const totals = document.querySelector("#nutritionTotals");
    for (const [label, key, unit] of [["Kalorien", "kcal", "kcal"], ["Kohlenhydrate", "carbs_g", "g"], ["Protein", "protein_g", "g"], ["Fett", "fat_g", "g"]]) {
      const tile = document.createElement("div");
      tile.className = "nutrition-total";
      const value = document.createElement("strong");
      const known = day.entries.some((entry) => entry[key] != null);
      const total = day[`total_${key}`];
      value.textContent = `${known && total != null ? nutritionNumber(total) : "–"} ${unit}`;
      const caption = document.createElement("span");
      caption.textContent = label + (known && day.entries.some((entry) => entry[key] == null) ? " · unvollständig" : "");
      tile.append(value, caption);
      totals.append(tile);
    }
    document.querySelector("#nutritionEntries").replaceChildren(...day.entries.map((item) => nutritionCard(item, false)));
    const templates = document.querySelector("#nutritionTemplates");
    templates.replaceChildren(...saved.templates.map((item) => nutritionCard(item, true)));
    void loadNutritionFueling();
    if (!saved.templates.length) templates.textContent = "Noch keine gespeicherten Mahlzeiten. Definiere dein erstes Standardfrühstück mit dem Coach.";
  } catch (error) {
    if (sequence === nutritionLoadSequence && generation === state.sessionGeneration) {
      status.textContent = `Ernährung konnte nicht geladen werden: ${error.message}`;
      clearNutritionExpenditure(`Tagesverbrauch konnte nicht geladen werden: ${error.message}`);
    }
  }
}

function nutritionFuelingSection() {
  let section = document.querySelector("#nutritionFueling");
  if (section) return section;
  section = document.createElement("section");
  section.id = "nutritionFueling";
  section.className = "nutrition-tools";
  section.setAttribute("aria-label", "Trainingsverpflegung");
  const heading = document.createElement("h3");
  heading.textContent = "Trainingsverpflegung";
  const label = document.createElement("label");
  label.textContent = "Geplante Ausdauereinheit";
  const select = document.createElement("select");
  select.id = "nutritionFuelingUnit";
  label.append(select);
  const output = document.createElement("div");
  output.id = "nutritionFuelingPlan";
  output.setAttribute("aria-live", "polite");
  section.append(heading, label, output);
  document.querySelector("#nutritionTemplates").insertAdjacentElement("afterend", section);
  select.addEventListener("change", () => void loadNutritionFuelingPlan(select.value));
  return section;
}

function nutritionFuelingRange(range, unit) {
  if (Array.isArray(range)) return `${range[0]}\u2013${range[1]} ${unit}`;
  return range == null ? "unbekannt" : `${range} ${unit}`;
}

function renderNutritionFuelingPlan(plan) {
  const output = document.querySelector("#nutritionFuelingPlan");
  const rows = [];
  const add = (tag, text, className) => { const node = document.createElement(tag); node.textContent = text; if (className) { node.className = className; }
    rows.push(node); };
  if (plan.status !== "suggestion") {
    add("p", "Die Dauer dieser Einheit ist unbekannt. Ohne Dauer gibt es keinen Vorschlag.", "muted");
  } else {
    add("p", `${plan.name || "Einheit"} \u00b7 ${plan.date ? dateLabel(plan.date) : "Datum unbekannt"} \u00b7 ${nutritionNumber(plan.duration_hours * 60)} min`);
    add("p", `Kohlenhydrate: ${nutritionFuelingRange(plan.carbs_g_per_hour, "g/h")} \u00b7 Fl\u00fcssigkeit: ${nutritionFuelingRange(plan.fluid_ml_per_hour, "ml/h")}`);
    (plan.timeline || []).forEach((line) => add("p", line, "fine-print"));
    add("p", `Vertr\u00e4glichkeit: ${plan.tolerance}`, "fine-print");
  }
  if (plan.saved_plan) {
    const saved = plan.saved_plan;
    add("p", `Gespeicherter Plan: ${saved.carbs_g_per_hour} g/h Kohlenhydrate, ${saved.fluid_ml_per_hour} ml/h Fl\u00fcssigkeit${plan.saved_stale ? " \u00b7 Einheit hat sich seitdem ge\u00e4ndert, bitte pr\u00fcfen" : ""}`);
  }
  add("p", "Anpassen oder speichern kannst du den Plan mit dem Coach. Erfasst wird dabei kein Verzehr.", "fine-print");
  output.replaceChildren(...rows);
}

async function loadNutritionFuelingPlan(unitId) {
  const output = document.querySelector("#nutritionFuelingPlan");
  if (!unitId) { output.replaceChildren(); return; }
  try {
    renderNutritionFuelingPlan(await api(`/api/nutrition/fueling?planned_unit_id=${encodeURIComponent(unitId)}`));
  } catch (error) {
    output.textContent = `Verpflegung konnte nicht geladen werden: ${error.message}`;
  }
}

async function loadNutritionFueling() {
  const section = nutritionFuelingSection();
  const select = section.querySelector("select");
  try {
    const { units = [] } = await api("/api/nutrition/fueling");
    const today = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const upcoming = units.filter((unit) => !unit.date || String(unit.date).slice(0, 10) >= today).sort((a, b) => String(a.date).localeCompare(String(b.date)));
    select.replaceChildren(...upcoming.map((unit) => { const option = document.createElement("option"); option.value = unit.id; option.textContent = `${unit.date ? dateLabel(String(unit.date).slice(0, 10)) : "?"} \u00b7 ${unit.name || "Einheit"}`; return option; }));
    section.hidden = !upcoming.length;
    if (upcoming.length) await loadNutritionFuelingPlan(select.value);
  } catch {
    // Intentionally ignored: fueling is optional and the diary remains usable.
    section.hidden = true;
  }
}
document.querySelector("#nutritionDate").addEventListener("change", () => void loadNutrition());
for (const [id, offset] of [["nutritionPrevious", -1], ["nutritionNext", 1]]) {
  document.getElementById(id).addEventListener("click", () => {
    const input = document.querySelector("#nutritionDate");
    if (!input.value) return;
    const day = new Date(`${input.value}T12:00:00Z`);
    day.setUTCDate(day.getUTCDate() + offset);
    input.value = day.toISOString().slice(0, 10);
    void loadNutrition();
  });
}
document.querySelector("#nutritionToday").addEventListener("click", () => { document.querySelector("#nutritionDate").value = ""; void loadNutrition(); });

function resetNutritionView() {
  ++nutritionLoadSequence;
  ++nutritionProductLoadSequence;
  stopNutritionBarcode();
  document.querySelector("#nutritionBarcodeDialog")?.close();
  document.querySelector("#nutritionProductUseDialog")?.close();
  nutritionProductForUse = null;
  document.querySelector("#nutritionDate").value = "";
  for (const id of ["nutritionEntries", "nutritionTemplates", "nutritionTotals", "nutritionStatus", "nutritionProducts", "nutritionProductStatus", "nutritionExpenditureTotals", "nutritionExpenditureStatus", "nutritionExpenditureDate"]) document.getElementById(id)?.replaceChildren();
  const editor = document.querySelector("#nutritionExtraction"); if (editor) { editor.replaceChildren(); editor.hidden = true; }
  const query = document.querySelector("#nutritionProductQuery"); if (query) query.value = "";
}

let nutritionBarcodeStream = null;
let nutritionBarcodeFrame = null;
let nutritionBarcodeDetector = null;
let nutritionBarcodeSession = 0;
let nutritionProductForUse = null;
let nutritionProductLoadSequence = 0;

function nutritionProductValue(value) {
  return value == null || value === "" ? "" : String(value);
}

function normalizeNutritionProduct(product = {}) {
  const per100 = product.per_100 || {};
  const source = product.source === "Open Food Facts" || product.source === "open_food_facts" ? "open_food_facts" : (product.source || "packaging_label");
  const normalized = {
    ...product,
    brand: product.brand || product.brands || "",
    kcal: product.kcal ?? per100.kcal ?? null,
    carbs_g: product.carbs_g ?? per100.carbs_g ?? null,
    protein_g: product.protein_g ?? per100.protein_g ?? null,
    fat_g: product.fat_g ?? per100.fat_g ?? null,
    confidence: product.confidence ?? product.extraction_confidence ?? null,
    source_url: product.source_url || "",
    source,
  };
  if (source === "open_food_facts" && String(product.id || "").startsWith("off:")) {
    normalized.external_id = normalized.external_id || product.id;
    const barcode = /^off:(\d{8,14})$/.exec(String(product.id));
    if (barcode && !normalized.barcode) normalized.barcode = barcode[1];
    delete normalized.id;
  }
  return normalized;
}

function nutritionProductForm(product = {}) {
  const form = document.createElement("form");
  form.className = "nutrition-product-form";
  form.innerHTML = `<input name="id" type="hidden"><input name="source" type="hidden"><input name="source_url" type="hidden"><input name="external_id" type="hidden"><input name="provenance" type="hidden"><input name="warnings" type="hidden"><label>Marke<input name="brand" maxlength="120"></label><label>EAN/GTIN<input name="barcode" inputmode="numeric" pattern="[0-9]{8,14}" maxlength="14"></label><div class="nutrition-product-grid"><label>Name<input name="name" required maxlength="160"></label><label>kcal<input name="kcal" type="number" min="0" step="0.1"></label><label>Kohlenhydrate (g)<input name="carbs_g" type="number" min="0" step="0.1"></label><label>Protein (g)<input name="protein_g" type="number" min="0" step="0.1"></label><label>Fett (g)<input name="fat_g" type="number" min="0" step="0.1"></label><label>Bezugsmenge<input name="basis_amount" type="number" min="0.1" step="0.1" value="100"></label><label>Einheit<select name="basis_unit"><option value="g">pro 100 g</option><option value="ml">pro 100 ml</option><option value="portion">pro Portion</option></select></label></div><p class="fine-print" data-extraction-confidence></p><p class="fine-print">Leere Nährwerte bleiben unbekannt. Bitte prüfe jede erkannte Zahl vor dem Speichern.</p><div class="nutrition-actions"><button type="submit" class="push-button">Produkt lokal speichern</button><button type="button" class="secondary-button" data-product-cancel>Abbrechen</button></div>`;
  populateNutritionProductFields(form, product);
  form.elements.source.value = product.source || "packaging_label";
  const confidenceInput = document.createElement("input"); confidenceInput.name = "confidence"; confidenceInput.type = "hidden"; confidenceInput.value = nutritionProductValue(product.confidence); form.append(confidenceInput);
  form.elements.basis_amount.required = true;
  form.elements.basis_unit.required = true;
  setNutritionProductBasis(form, product);
  setNutritionProductMetadata(form, product);
  setNutritionProductConfidence(form, product);
  return form;
}

function populateNutritionProductFields(form, product) {
  for (const [key, value] of Object.entries(product)) {
    const field = form.elements.namedItem(key);
    if (field) field.value = nutritionProductValue(value);
  }
  const grid = form.querySelector(".nutrition-product-grid");
  for (const [key, label] of [["sugar_g", "Zucker (g)"], ["fiber_g", "Ballaststoffe (g)"], ["salt_g", "Salz (g)"]]) {
    const wrapper = document.createElement("label");
    wrapper.append(document.createTextNode(label));
    const input = document.createElement("input"); input.name = key; input.type = "number"; input.min = "0"; input.step = "0.1";
    input.value = nutritionProductValue(product[key]); wrapper.append(input); grid.append(wrapper);
  }
}

function setNutritionProductBasis(form, product) {
  if (!product.basis_amount) form.elements.basis_amount.value = "";
  if (product.basis_unit) return;
  const option = document.createElement("option"); option.value = ""; option.textContent = "Bezugsmenge auswählen"; option.selected = true; option.disabled = true;
  form.elements.basis_unit.prepend(option);
  form.elements.basis_unit.value = "";
}

function setNutritionProductMetadata(form, product) {
  for (const key of ["source_url", "external_id"]) form.elements[key].value = nutritionProductValue(product[key]);
  const provenance = product.provenance && typeof product.provenance === "object" ? product.provenance : { kind: product.source || product.provenance || "packaging_label", requires_confirmation: true };
  form.elements.provenance.value = JSON.stringify(provenance);
  form.elements.warnings.value = JSON.stringify(product.warnings || []);
}

function setNutritionProductConfidence(form, product) {
  const confidence = Number(product.confidence);
  const warning = Number.isFinite(confidence) && confidence < 0.65 ? "Geringe Erkennungssicherheit. Werte besonders sorgfältig prüfen." : "Erkannte Werte bitte mit dem Etikett abgleichen.";
  const warningDetails = product.warnings?.length ? ` Hinweise: ${product.warnings.join("; ")}` : "";
  const confidenceLine = form.querySelector("[data-extraction-confidence]");
  confidenceLine.textContent = Number.isFinite(confidence) ? `Erkennungssicherheit: ${Math.round(confidence * 100)} %. ${warning}` : warning + warningDetails;
  for (const [field, score] of Object.entries(product.field_confidence || {})) {
    const input = form.elements.namedItem(field);
    if (input && Number(score) < 0.65) { input.classList.add("nutrition-low-confidence"); input.title = "Unsichere Fotoerkennung; bitte am Etikett prüfen."; }
  }
}

function nutritionProductPayload(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  const source = data.source || "packaging_label";
  let provenance;
  try { provenance = JSON.parse(data.provenance || "{}"); } catch { provenance = {}; }
  const payload = { ...data, source, provenance: { ...(provenance && typeof provenance === "object" ? provenance : {}), kind: source, confirmed: true } };
  try { payload.warnings = JSON.parse(data.warnings || "[]"); } catch { payload.warnings = []; }
  for (const key of ["kcal", "carbs_g", "protein_g", "fat_g", "sugar_g", "fiber_g", "salt_g", "basis_amount", "confidence"]) payload[key] = data[key] === "" ? null : Number(data[key]);
  return payload;
}

function renderNutritionProducts(products, { local = true } = {}) {
  const target = document.querySelector("#nutritionProducts");
  if (!target) return;
  target.replaceChildren();
  if (!products?.length) { target.textContent = "Keine lokalen Produkte gefunden."; return; }
  for (const rawProduct of products) {
    const product = normalizeNutritionProduct(rawProduct);
  const card = document.createElement("article");
    card.className = "nutrition-card nutrition-product-card";
    const title = document.createElement("h3"); title.textContent = [product.brand, product.name].filter(Boolean).join(" · ") || "Unbenanntes Produkt";
    const kcalLabel = product.kcal == null ? "kcal unbekannt" : `${product.kcal} kcal`;
    const detail = document.createElement("p"); detail.textContent = `${kcalLabel} · KH ${product.carbs_g ?? "–"} g · Protein ${product.protein_g ?? "–"} g · Fett ${product.fat_g ?? "–"} g`;
    const sourceLabel = product.source === "packaging_label" ? "Verpackungsangabe" : (product.source || "Lokales Produkt");
    const barcodeLabel = product.barcode ? ` · EAN ${product.barcode}` : "";
    const source = document.createElement("small"); source.textContent = sourceLabel + barcodeLabel;
    const basis = document.createElement("small"); basis.textContent = product.basis_amount ? `Basis: ${product.basis_amount} ${product.basis_unit || "g"}` : "Bezugsmenge unbekannt";
    card.append(title, detail, source, basis);
    if (!local || product.local === false) {
      const button = document.createElement("button"); button.type = "button"; button.className = "secondary-button"; button.textContent = "Lokal speichern";
      button.addEventListener("click", () => saveNutritionProduct(product)); card.append(button);
    } else if (product.id) {
      const actions = document.createElement("div"); actions.className = "nutrition-actions";
      const use = document.createElement("button"); use.type = "button"; use.className = "push-button"; use.textContent = "In Mahlzeit erfassen";
      use.addEventListener("click", () => useNutritionProduct(product));
      const edit = document.createElement("button"); edit.type = "button"; edit.className = "secondary-button"; edit.textContent = "Bearbeiten"; edit.addEventListener("click", () => saveNutritionProduct(product));
      const archive = document.createElement("button"); archive.type = "button"; archive.className = "secondary-button"; archive.textContent = "Archivieren";
      archive.addEventListener("click", async () => {
        if (!await requestConfirmation(`Produkt „${product.name}“ archivieren?`)) return;
        try { await api("/api/nutrition/products/archive", { method: "POST", body: JSON.stringify({ id: product.id, confirmed: true }) }); await loadNutritionProducts(document.querySelector("#nutritionProductQuery").value.trim()); }
        catch (error) { document.querySelector("#nutritionProductStatus").textContent = `Produkt konnte nicht archiviert werden: ${error.message}`; }
      });
      actions.append(use, edit, archive); card.append(actions);
    }
    target.append(card);
  }
}

function useNutritionProduct(product) {
  const unit = nutritionProductUnit(product);
  nutritionProductForUse = product;
  const dialog = document.querySelector("#nutritionProductUseDialog");
  document.querySelector("#nutritionProductUseName").textContent = product.name || "Lokales Produkt";
  document.querySelector("#nutritionProductUseUnit").textContent = `(in ${unit})`;
  const amount = document.querySelector("#nutritionProductUseAmount"); amount.value = product.basis_amount || 100;
  dialog.showModal();
}

function nutritionProductUnit(product = {}) {
  const unit = String(product.basis_unit || "g").toLowerCase();
  return ["g", "ml", "portion"].includes(unit) ? unit : "g";
}

async function createNutritionProductDraft() {
  const product = nutritionProductForUse;
  if (!product) return;
  const unit = nutritionProductUnit(product);
  const amount = document.querySelector("#nutritionProductUseAmount").value;
  const input = document.querySelector("#messageInput");
  if (!input) return;
  if (input.value.trim() && !await requestConfirmation("Dein aktueller Coach-Entwurf wird durch den Produktverzehr ersetzt. Fortfahren?", { title: "Entwurf ersetzen?" })) return;
  input.value = `Erfasse ${amount} ${unit} als Mahlzeit (Produkt-ID: ${product.id}).`;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  state.chatDraftDirty = true;
  document.querySelector("#nutritionProductUseDialog")?.close();
  nutritionProductForUse = null;
  void AppRouter.navigate("coach", { historyMode: "push" });
  jumpToChatComposer();
}

async function loadNutritionProducts(query = "") {
  const sequence = ++nutritionProductLoadSequence;
  const generation = state.sessionGeneration;
  const status = document.querySelector("#nutritionProductStatus");
  try {
    status.textContent = "Produkte werden gesucht …";
    const params = query ? `?q=${encodeURIComponent(query)}` : "";
    const result = await api(`/api/nutrition/products${params}`);
    if (sequence !== nutritionProductLoadSequence || generation !== state.sessionGeneration) return;
    renderNutritionProducts(result.products || []);
    status.textContent = result.products?.length ? "" : "Keine lokalen Produkte gefunden.";
  } catch (error) { if (sequence === nutritionProductLoadSequence && generation === state.sessionGeneration) status.textContent = `Produktsuche fehlgeschlagen: ${error.message}`; }
}

async function saveNutritionProduct(product) {
  const generation = state.sessionGeneration;
  const editor = document.querySelector("#nutritionExtraction");
  const form = product instanceof HTMLFormElement ? product : nutritionProductForm(normalizeNutritionProduct(product));
  if (product instanceof HTMLFormElement) {
    try {
      const payload = nutritionProductPayload(form);
      const saved = await api("/api/nutrition/products", { method: payload.id ? "PUT" : "POST", body: JSON.stringify({ ...payload, confirmed: true }) });
      if (generation !== state.sessionGeneration) return;
      editor.hidden = true; editor.replaceChildren(); document.querySelector("#nutritionProductStatus").textContent = `Produkt „${saved.product?.name || "Produkt"}“ lokal gespeichert.`; await loadNutritionProducts();
    } catch (error) { if (generation === state.sessionGeneration) document.querySelector("#nutritionProductStatus").textContent = `Produkt konnte nicht gespeichert werden: ${error.message}`; }
    return;
  }
  editor.replaceChildren(); editor.append(form); editor.hidden = false;
  form.addEventListener("submit", (event) => { event.preventDefault(); void saveNutritionProduct(form); });
  form.querySelector("[data-product-cancel]").addEventListener("click", () => { editor.hidden = true; editor.replaceChildren(); });
}

async function extractNutritionProduct(file) {
  const generation = state.sessionGeneration;
  const status = document.querySelector("#nutritionProductStatus");
  try {
    status.textContent = "Nährwerttabelle wird gelesen …";
    const prepared = await prepareNutritionImage(file);
    if (generation !== state.sessionGeneration) return;
    const result = await api("/api/nutrition/products/extract", { method: "POST", body: JSON.stringify({ image_data_url: prepared.dataUrl }) });
    if (generation !== state.sessionGeneration) return;
    const extraction = {};
    const candidate = result.candidate || result.extraction;
    if (candidate && typeof candidate === "object") Object.assign(extraction, candidate);
    extraction.provenance = result.provenance || "packaging_label";
    extraction.source = "packaging_label";
    await saveNutritionProduct(extraction);
    status.textContent = "Bitte erkannte Werte prüfen und ausdrücklich speichern.";
  } catch (error) { if (generation === state.sessionGeneration) status.textContent = `Foto konnte nicht verarbeitet werden: ${error.message}`; }
}

async function lookupNutritionProduct(barcode) {
  const generation = state.sessionGeneration;
  const clean = String(barcode || "").replace(/\D/g, "");
  if (!/^\d{8,14}$/.test(clean)) { document.querySelector("#nutritionBarcodeStatus").textContent = "Bitte eine gültige EAN mit 8 bis 14 Ziffern eingeben."; return; }
  try {
    document.querySelector("#nutritionBarcodeStatus").textContent = "Produkt wird gesucht …";
    const result = await api("/api/nutrition/products/lookup", { method: "POST", body: JSON.stringify({ barcode: clean }) });
    if (generation !== state.sessionGeneration) return;
    document.querySelector("#nutritionBarcodeDialog")?.close();
    const product = result.product || result.foods?.[0] || result.products?.[0] || null;
    const isLocal = result.local !== false && result.source !== "open_food_facts";
    renderNutritionProducts(product ? [{ ...product, local: isLocal }] : [], { local: isLocal });
    document.querySelector("#nutritionProductStatus").textContent = isLocal ? "Lokales Produkt gefunden." : "Online-Treffer gefunden. Prüfe ihn und speichere ihn lokal.";
    if (product && !isLocal) await saveNutritionProduct(normalizeNutritionProduct({ ...product, source: result.source || product.source || "open_food_facts" }));
  } catch (error) { if (generation === state.sessionGeneration) document.querySelector("#nutritionBarcodeStatus").textContent = `Produktsuche fehlgeschlagen: ${error.message}`; }
}

function stopNutritionBarcode() {
  nutritionBarcodeSession += 1;
  if (nutritionBarcodeFrame) cancelAnimationFrame(nutritionBarcodeFrame);
  nutritionBarcodeFrame = null;
  nutritionBarcodeStream?.getTracks().forEach((track) => track.stop());
  nutritionBarcodeStream = null;
  const video = document.querySelector("#nutritionBarcodeVideo"); if (video) video.srcObject = null;
}

async function scanNutritionBarcode() {
  const dialog = document.querySelector("#nutritionBarcodeDialog");
  const video = document.querySelector("#nutritionBarcodeVideo");
  const status = document.querySelector("#nutritionBarcodeStatus");
  dialog.showModal();
  const session = ++nutritionBarcodeSession;
  const generation = state.sessionGeneration;
  if (!("BarcodeDetector" in globalThis) || !navigator.mediaDevices?.getUserMedia) { status.textContent = "Automatisches Scannen wird hier nicht unterstützt. Gib die EAN manuell ein."; return; }
  try {
    nutritionBarcodeDetector = new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e"] });
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
    if (session !== nutritionBarcodeSession || !dialog.open || generation !== state.sessionGeneration) { stream.getTracks().forEach((track) => track.stop()); return; }
    nutritionBarcodeStream = stream;
    video.srcObject = nutritionBarcodeStream; await video.play(); status.textContent = "Barcode vor die Kamera halten …";
    const scan = async () => {
      if (!dialog.open || session !== nutritionBarcodeSession || generation !== state.sessionGeneration) return;
      try { const codes = await nutritionBarcodeDetector.detect(video); if (codes[0]?.rawValue) { document.querySelector("#nutritionBarcodeManual").value = codes[0].rawValue; await lookupNutritionProduct(codes[0].rawValue); return; } } catch (_) { /* continue until cancelled */ }
      if (session !== nutritionBarcodeSession || generation !== state.sessionGeneration) return;
      nutritionBarcodeFrame = requestAnimationFrame(scan);
    };
    nutritionBarcodeFrame = requestAnimationFrame(scan);
  } catch (error) { if (session === nutritionBarcodeSession && generation === state.sessionGeneration) { status.textContent = `Kamera nicht verfügbar. Gib die EAN manuell ein. (${error.message})`; stopNutritionBarcode(); } }
}

document.querySelector("#nutritionProductSearch")?.addEventListener("submit", (event) => { event.preventDefault(); void loadNutritionProducts(document.querySelector("#nutritionProductQuery").value.trim()); });
document.querySelector("#nutritionLabelButton")?.addEventListener("click", () => document.querySelector("#nutritionLabelInput").click());
document.querySelector("#nutritionProductManual")?.addEventListener("click", () => saveNutritionProduct({ source: "manual", basis_amount: 100, basis_unit: "g" }));
document.querySelector("#nutritionLabelInput")?.addEventListener("change", (event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void extractNutritionProduct(file); });
document.querySelector("#nutritionBarcodeButton")?.addEventListener("click", () => void scanNutritionBarcode());
document.querySelector("#nutritionBarcodeCancel")?.addEventListener("click", () => document.querySelector("#nutritionBarcodeDialog")?.close());
document.querySelector("#nutritionBarcodeDialog")?.addEventListener("close", stopNutritionBarcode);
document.querySelector("#nutritionBarcodeForm")?.addEventListener("submit", (event) => { event.preventDefault(); void lookupNutritionProduct(document.querySelector("#nutritionBarcodeManual").value); });
document.querySelector("#nutritionProductUseCancel")?.addEventListener("click", () => document.querySelector("#nutritionProductUseDialog")?.close());
document.querySelector("#nutritionProductUseForm")?.addEventListener("submit", (event) => { event.preventDefault(); void createNutritionProductDraft(); });
function handleNutritionRoute(route) {
  if (route !== "nutrition/products") { stopNutritionBarcode(); document.querySelector("#nutritionBarcodeDialog")?.close(); }
}
globalThis.AppNutrition = Object.freeze({ handleRoute: handleNutritionRoute });
globalThis.addEventListener("pagehide", stopNutritionBarcode);
document.addEventListener("visibilitychange", () => { if (document.hidden) stopNutritionBarcode(); });
