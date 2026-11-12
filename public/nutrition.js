// Read-only nutrition views; every write remains an explicit Coach request.
let nutritionLoadSequence = 0;
let nutritionHistoryPeriod = "fortnight";

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
  const week = route === "nutrition/week";
  const products = route === "nutrition/products";
  const body = route === "nutrition/body";
  const names = { "nutrition/diary": "Tagebuch", "nutrition/week": "Verlauf", "nutrition/body": "Körper", "nutrition/products": "Produkte" };
  document.querySelector("#nutritionRefreshButton").setAttribute("aria-label", `Ernährung aktualisieren: ${names[route] || "Tagebuch"}`);
  document.querySelector("#nutritionDiary").hidden = week || products || body;
  document.querySelector("#bodyAnalysisCharts").hidden = !body;
  document.querySelector("#nutritionStatus").hidden = week || products || body;
  document.querySelector("#nutritionWeek").hidden = !week;
  document.querySelector("#nutritionProductsPanel").hidden = !products;
  document.querySelectorAll("[data-nutrition-segment]").forEach((link) => {
    let activeSegment = "diary";
    if (week) activeSegment = "week";
    if (body) activeSegment = "body";
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
  return Number.isFinite(number) ? AppFormat.number(number, { digits: 1 }) : String(value);
}

// A diary write reports its text with "Rückgängig" while the change can still be undone.
function showNutritionReceipt(status, message, change, afterUndo) {
  const text = h("span", null, `${message} `);
  status.replaceChildren(text);
  if (!change?.id) return;
  const undo = h("button", { type: "button", className: "message-undo" }, "Rückgängig");
  undo.addEventListener("click", async () => {
    undo.disabled = true;
    try {
      await api("/api/change-history/undo", { method: "POST", body: JSON.stringify({ change_id: change.id, expected_current_hash: change.after_hash }) });
      await afterUndo?.();
      status.textContent = "Zurückgenommen.";
    } catch (error) {
      undo.disabled = false;
      text.textContent = `${error.message} `;
    }
  });
  status.append(undo);
}

async function deleteNutritionEntry(item) {
  if (!await requestConfirmation(`Mahlzeit „${item.description}“ wirklich löschen?`, { title: "Mahlzeit löschen?", confirmLabel: "Löschen" })) return;
  const status = document.querySelector("#nutritionStatus");
  try {
    const result = await api("/api/nutrition/entry/delete", { method: "POST", body: JSON.stringify({ id: item.id }) });
    await loadNutrition({ preserve: true });
    showNutritionReceipt(status, "Mahlzeit gelöscht.", result.change, () => loadNutrition({ preserve: true }));
  } catch (error) { status.textContent = `Mahlzeit konnte nicht gelöscht werden: ${error.message}`; }
}

// "Open Food Facts" or "Yazio" for a product from a database; "" for an own product.
function nutritionDatabaseLabel(product) {
  if (!product?.origin || product.origin === "own") return "";
  return { open_food_facts: "Open Food Facts", yazio: "Yazio" }[product.origin] || "Datenbank";
}

function nutritionComponentSource(basis) {
  const kind = basis?.kind;
  if (kind === "local_product" || kind === "product") {
    const product = basis.product || basis;
    const database = nutritionDatabaseLabel(product);
    const source = product.source === "packaging_label" ? "Verpackungsangabe" : product.source;
    const label = product.product_name || product.name || (database ? "Datenbankprodukt" : "Gespeichertes Produkt");
    if (database) return `Datenbankprodukt: ${label} · ${database}`;
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

// "1890 kcal" keeps its text; the unit is set smaller than the value (#1789).
function setValueWithUnit(element, text) {
  const split = text.lastIndexOf(" ");
  if (split < 1) { element.textContent = text; return element; }
  element.replaceChildren(text.slice(0, split), " ", h("span", "nutrition-unit", text.slice(split + 1)));
  return element;
}

function nutritionBasisLabel(basis, item, sourceLabel) {
  if (basis?.kind === "composite") return "";
  if (basis?.kind === "database") {
    return "Datenbankberechnung · " + basis.ingredients.map((food) => `${food.source}: ${food.name}, ${food.amount} ${food.unit} (Basis 100 ${food.basis_unit})`).join("; ");
  }
  if (basis?.kind === "product" || basis?.kind === "local_product") {
    const product = basis.product || basis;
    const name = product.product_name || product.name || "Produkt";
    const database = nutritionDatabaseLabel(product);
    const source = database || product.source ? ` (${database || product.source})` : "";
    const amount = basis.amount != null ? ` · ${basis.amount} ${basis.unit || "g"}` : "";
    return `${database ? "Datenbankprodukt" : "Lokales Produkt"} · ${name}${source}${amount}`;
  }
  if (basis?.kind === "manual_correction") return "Manuell korrigierte Nährwerte";
  if (basis?.kind === "packaging_label") return "Verpackungsangabe";
  return sourceLabel;
}

function nutritionComponentDetails(item) {
  const components = item.nutrition_basis?.kind === "composite" ? item.nutrition_basis.components : [];
  if (!Array.isArray(components) || !components.length) return null;
  return h("details", "nutrition-components",
    h("summary", null, `Zutaten anzeigen (${components.length})`),
    h("ul", "nutrition-component-list", components.map((component) => h("li", null,
      h("strong", null, component.name || "Unbenannte Zutat"),
      h("span", null, ` · ${component.amount ?? "–"} ${component.unit || ""}`.trim()),
      h("span", null, ` · ${nutritionNumber(component.kcal)} kcal · KH ${nutritionNumber(component.carbs_g)} g · Protein ${nutritionNumber(component.protein_g)} g · Fett ${nutritionNumber(component.fat_g)} g`),
      h("small", null, nutritionComponentSource(component.nutrition_basis))))));
}

function nutritionMealTitle(item) {
  const mealLabels = { breakfast: "Frühstück", lunch: "Mittagessen", dinner: "Abendessen", snack: "Snack" };
  const mealLabel = mealLabels[item.meal_type] || "Mahlzeit";
  const mealTime = item.logged_time_known === false ? "" : String(item.logged_at).split("T")[1]?.slice(0, 5) || "";
  return mealTime ? `${mealTime} · ${mealLabel}` : mealLabel;
}

function nutritionCard(item, template) {
  const sourceLabels = { coach: "Coach-Schätzung", photo: "Foto-Schätzung", voice: "Sprach-Schätzung", manual: "Manuelle Angabe" };
  const sourceLabel = sourceLabels[item.source] || "Erfasst";
  const syncLabel = item.sync_state === "synced" ? " · Synchronisiert" : " · Lokal";
  const basisLabel = nutritionBasisLabel(item.nutrition_basis, { template, syncLabel }, sourceLabel);
  // The default (typed in by hand, stored locally) is not repeated under every meal; any other source or state is shown.
  const isDefaultSource = !template && item.source === "manual" && item.sync_state !== "synced" && basisLabel === sourceLabel;
  const sourceText = basisLabel && !isDefaultSource ? `${basisLabel}${template ? "" : syncLabel}` : "";
  const card = h("article", "nutrition-card",
    h("h3", null, template ? item.name : nutritionMealTitle(item)),
    h("p", null, item.description),
    h("p", null, `${nutritionNumber(item.kcal)} kcal · KH ${nutritionNumber(item.carbs_g)} g · Protein ${nutritionNumber(item.protein_g)} g · Fett ${nutritionNumber(item.fat_g)} g${template ? " / Portion" : ""}`),
    sourceText ? h("small", null, sourceText) : null);
  if (!template) {
    const details = nutritionComponentDetails(item);
    if (details) card.append(details);
    const remove = h("button", { type: "button", className: "secondary-button", "aria-label": `Mahlzeit löschen: ${item.description}` }, "Löschen");
    remove.addEventListener("click", () => void deleteNutritionEntry(item));
    card.append(remove);
  }
  return card;
}

function nutritionExpenditureSection() {
  let section = document.querySelector("#nutritionExpenditure");
  if (section) return section;
  section = h("section", { id: "nutritionExpenditure", className: "nutrition-tools", "aria-label": "Garmin-Energieverbrauch" },
    h("h3", null, "Energieverbrauch"),
    h("output", { id: "nutritionExpenditureStatus", className: "tab-sync-detail", "aria-live": "polite" }),
    h("div", { id: "nutritionExpenditureTotals", className: "nutrition-totals" }),
    h("p", { id: "nutritionExpenditureDate", className: "fine-print" }));
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
  section.hidden = false;
  section.querySelector("#nutritionExpenditureStatus").textContent = message;
  section.querySelector("#nutritionExpenditureTotals").replaceChildren();
  section.querySelector("#nutritionExpenditureDate").textContent = "";
}

function renderNutritionExpenditure(expenditure, selectedDate) {
  const section = nutritionExpenditureSection();
  section.hidden = false;
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

  // Absent values return null and render muted as "nicht erfasst" (#1783).
  const formatKcal = (rawValue) => {
    const value = rawValue == null || rawValue === "" ? null : Number(rawValue);
    return value != null && Number.isFinite(value) ? `${AppFormat.number(value, { digits: 0 })} kcal` : null;
  };
  const kcalValue = (rawValue) => {
    const value = h("strong");
    const text = formatKcal(rawValue);
    if (text == null) markValueMissing(value); else setValueWithUnit(value, text);
    return value;
  };
  const componentTile = (rawValue, caption) => h("div", "nutrition-total", kcalValue(rawValue), h("span", null, caption));
  const totalTile = componentTile(expenditure?.total_kcal, "Tagesverbrauch");
  totalTile.style.gridColumn = "1 / -1";
  const projected = expenditure?.projected_total_kcal;
  const hasProjection = projected != null && Number.isFinite(Number(projected));
  const projectionTile = hasProjection ? componentTile(projected, "Prognose Tagesverbrauch") : null;
  if (projectionTile) {
    projectionTile.style.gridColumn = "1 / -1";
    projectionTile.lastElementChild.append(" ", createEstimateChip());
  }
  totals.replaceChildren(
    totalTile,
    ...(projectionTile ? [projectionTile] : []),
    componentTile(expenditure?.active_kcal, "Aktivkalorien"),
    componentTile(expenditure?.resting_kcal, "Grundumsatz"),
  );

  const syncedAt = nutritionExpenditureTimestamp(expenditure?.synced_at);
  const fetchedAt = nutritionExpenditureTimestamp(expenditure?.fetched_at);
  date.textContent = "";
  if (syncedAt) date.textContent = `Sync: ${syncedAt}`;
  else if (fetchedAt) date.textContent = `Abgerufen: ${fetchedAt}`;
  if (projectionTile) {
    projectionTile.title = `Grundumsatz vom ${nutritionExpenditureDate(expenditure.projection_reference_date)} (${formatKcal(expenditure.projection_resting_kcal) ?? "nicht erfasst"}) + bisherige Aktivkalorien (${formatKcal(expenditure.active_kcal) ?? "nicht erfasst"}), eigene Schätzung`;
  }
}

function appendNutritionTotals(totals, day) {
  // Empty days report zero totals, which are unknown, so the tiles stay "nicht erfasst".
  const hasEntries = Number(day.entry_count) > 0;
  for (const [label, key, unit] of [["Kalorien", "kcal", "kcal"], ["Kohlenhydrate", "carbs_g", "g"], ["Protein", "protein_g", "g"], ["Fett", "fat_g", "g"], ["Zucker", "sugar_g", "g"], ["Salz", "salt_g", "g"]]) {
    const tile = nutritionTotalTile(label, key, unit, day, hasEntries);
    if (key === "kcal") tile.classList.add("is-hero");
    if (key === "sugar_g" || key === "salt_g") tile.classList.add("is-minor");
    totals.append(tile);
  }
}

function nutritionTotalTile(label, key, unit, day, hasEntries) {
  const tile = h("div", "nutrition-total");
  const value = h("strong");
  const complete = hasEntries ? day[`total_${key}`] : null;
  const range = day.macro_ranges?.[key];
  if (complete != null && Array.isArray(range) && range.length === 2) {
    if (complete < range[0] && day.date < todayIso()) tile.classList.add("nutrition-below-range");
    else if (complete > range[1]) tile.classList.add("nutrition-above-range");
  }
  // A partial sum of known values is shown only with an explicit incompleteness label.
  const total = hasEntries ? (complete ?? day.known_macro_totals?.[key] ?? day.known_intake_totals?.[key]) : null;
  if (total == null) markValueMissing(value);
  else setValueWithUnit(value, `${nutritionNumber(total)} ${unit}`);
  tile.append(value, h("span", null, label + (complete == null && total != null ? " · unvollständig" : "")));
  return tile;
}

function appendNutritionMacroNote(totals, entriesWithoutMacros) {
  if (entriesWithoutMacros > 0) {
    totals.append(h("p", "nutrition-total-note", entriesWithoutMacros === 1 ? "1 Eintrag ohne vollständige Makros" : `${entriesWithoutMacros} Einträge ohne vollständige Makros`));
  }
}

function nutritionWeekValue(value, unit, signed = false) {
  if (value == null) return "Nicht verfügbar";
  const prefix = signed && value > 0 ? "+" : "";
  const suffix = unit ? ` ${unit}` : "";
  return `${prefix}${AppFormat.number(value, { digits: unit === "g" ? 1 : 0 })}${suffix}`;
}

function renderNutritionHistoryPeriod() {
  const root = document.querySelector("#nutritionHistoryPeriod");
  if (!root.childElementCount) root.append(analysisPeriodControls("Zeitraum für Ernährung", nutritionHistoryPeriod, (period) => {
    nutritionHistoryPeriod = period;
    void loadNutrition();
  }));
  root.querySelectorAll("button").forEach((button, index) => {
    button.setAttribute("aria-pressed", String(["fortnight", "twelveWeeks"][index] === nutritionHistoryPeriod));
  });
  document.querySelector("#nutritionRefreshButton").setAttribute("aria-label", `Ernährung aktualisieren: Verlauf, ${nutritionHistoryPeriod === "twelveWeeks" ? "12 Wochen" : "14 Tage"}`);
}

function nutritionChartDays(days) {
  if (days.length !== 84) return days;
  return Array.from({ length: 12 }, (_, index) => {
    const week = days.slice(index * 7, index * 7 + 7);
    const point = { date: week[0].date, end_date: week.at(-1).date };
    for (const key of ["intake_kcal", "expenditure_kcal"]) {
      const values = week.map((day) => day[key]).filter(Number.isFinite);
      point[`${key}_days`] = values.length;
      point[key] = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    }
    return point;
  });
}

// Days without intake and expenditure are shown as one row per run (#1789).
function nutritionChartRows(chartDays) {
  const rows = [];
  for (const day of chartDays) {
    if (Number.isFinite(day.intake_kcal) || Number.isFinite(day.expenditure_kcal)) { rows.push({ day }); continue; }
    const last = rows.at(-1);
    if (last?.empty) last.end = day.end_date || day.date;
    else rows.push({ empty: true, start: day.date, end: day.end_date || day.date });
  }
  return rows;
}

function nutritionEmptyRunRow({ start, end }) {
  const first = nutritionExpenditureDate(start).slice(0, 5);
  const last = nutritionExpenditureDate(end).slice(0, 5);
  return h("div", "nutrition-week-chart-day is-empty", h("strong", null, first === last ? first : `${first}–${last}`), h("span", null, "keine Daten"));
}

function nutritionChartDayRow(day, scale) {
  const row = h("div", "nutrition-week-chart-day",
    h("strong", { "aria-label": (day.end_date && `${nutritionExpenditureDate(day.date)} bis ${nutritionExpenditureDate(day.end_date)}`) || null }, nutritionExpenditureDate(day.date).slice(0, 5)));
  for (const [key, label, kind] of [["intake_kcal", "Aufnahme", "intake"], ["expenditure_kcal", "Verbrauch", "expenditure"]]) {
    const value = day[key];
    const track = h("span", "nutrition-week-chart-track");
    if (Number.isFinite(value) && value >= 0) {
      const bar = h("span", "nutrition-week-chart-bar");
      bar.style.width = `${value / scale * 100}%`;
      track.append(bar);
    } else track.classList.add("is-missing");
    const amountText = value == null ? "–" : nutritionWeekValue(value, "kcal");
    const coverage = day.end_date ? `${day[key + "_days"]} von 7 Tagen` : "";
    let ariaLabel = `${label}: ${amountText}${value == null ? " (keine Daten)" : ""}`;
    if (coverage) ariaLabel = `${label}: ${amountText}, ${coverage}`;
    row.append(h("div", { className: `nutrition-week-chart-series is-${kind}`, "aria-label": ariaLabel },
      track, h("span", null, amountText, coverage ? [h("br"), h("small", null, coverage)] : null)));
  }
  return row;
}

function renderNutritionWeek(week) {
  const dayCount = week.days.length;
  document.querySelector("#nutritionWeekPeriod").textContent = `${nutritionExpenditureDate(week.start_date)} – ${nutritionExpenditureDate(week.end_date)}`;
  const totals = document.querySelector("#nutritionWeekTotals");
  const balance = week.balance_kcal;
  let balanceLabel = "Bilanz";
  if (balance != null) {
    balanceLabel = "Ausgeglichene Bilanz";
    if (balance > 0) balanceLabel = "Kalorienüberschuss";
    if (balance < 0) balanceLabel = "Kaloriendefizit";
  }
  if (balance != null && week.balance_days < dayCount) balanceLabel = "Erfasste Teilbilanz";
  const items = [[balanceLabel, balance, "kcal", week.balance_days, true],
    ["Ø Kalorienbilanz pro Tag", week.balance_days > 0 && balance != null ? Math.sign(balance) * Math.round(Math.abs(balance / week.balance_days)) || 0 : null, "kcal", week.balance_days, true],
    ...[["Ø Aufnahme", "intake_kcal", "kcal"], ["Ø Verbrauch", "expenditure_kcal", "kcal"], ["Ø Kohlenhydrate", "carbs_g", "g"], ["Ø Protein", "protein_g", "g"], ["Ø Fett", "fat_g", "g"], ["Ø Zucker", "sugar_g", "g"], ["Ø Salz", "salt_g", "g"]].map(([label, key, unit]) => [label, week.averages[key].value, unit, week.averages[key].days, false])];
  totals.replaceChildren(...items.map(([label, value, unit, days, isBalance]) => {
    const number = h("strong");
    if (value == null) markValueMissing(number); else setValueWithUnit(number, nutritionWeekValue(value, unit, isBalance));
    return h("div", "nutrition-total", number, h("span", null, label), h("small", null, `${days} von ${dayCount} Tagen${isBalance && days < dayCount ? " · Teilbilanz" : ""}`));
  }));
  document.querySelector("#nutritionWeekStatus").textContent = week.balance_days === dayCount ? `Alle ${dayCount} Tage auswertbar.` : `${week.balance_days} von ${dayCount} Tagen mit Aufnahme und Gesamtverbrauch auswertbar. Für die übrigen Tage bleibt die Bilanz offen.`;
  const chartDays = nutritionChartDays(week.days);
  document.querySelector("#nutritionWeekChartHeading").textContent = dayCount === 84 ? "Wochendurchschnitte" : "Tagesverlauf";
  const scale = Math.max(1, ...chartDays.flatMap((day) => [day.intake_kcal, day.expenditure_kcal].filter((value) => Number.isFinite(value) && value >= 0)));
  document.querySelector("#nutritionWeekChart").replaceChildren(...nutritionChartRows(chartDays).map((entry) => (entry.empty ? nutritionEmptyRunRow(entry) : nutritionChartDayRow(entry.day, scale))));
  document.querySelector("#nutritionWeekChartSection").hidden = false;
  document.querySelector("#nutritionWeekDays").replaceChildren(...week.days.map((day) => h("tr", null,
    h("th", { scope: "row" }, nutritionExpenditureDate(day.date).slice(0, 5)),
    ...["intake_kcal", "expenditure_kcal", "balance_kcal"].map((key) => h("td", null, day[key] == null ? "–" : nutritionWeekValue(day[key], "", key === "balance_kcal"))))));
  document.querySelector("#nutritionWeekDetails").hidden = false;
}

// Renders the last loaded response at once; the fresh response replaces it.
function showCachedNutritionView(path, renderView) {
  const cached = readViewCache(path);
  if (!cached) return false;
  try {
    renderView(cached);
    return true;
  } catch { return false; }
}

function isCurrentNutritionWeekLoad(sequence, generation, cacheEpoch, expectedRoute, expectedView) {
  return sequence === nutritionLoadSequence
    && generation === state.sessionGeneration
    && cacheEpoch === viewCacheEpoch
    && (!expectedRoute || state.route === expectedRoute)
    && (!expectedView || nutritionHistoryPeriod === expectedView);
}

async function loadNutritionWeek(sequence, generation, preserve = false, expectedRoute = null, expectedView = null, throwOnError = false) {
  const path = `/api/nutrition/week?days=${nutritionHistoryPeriod === "twelveWeeks" ? 84 : 14}`;
  renderNutritionHistoryPeriod();
  const cacheEpoch = viewCacheEpoch;
  const status = document.querySelector("#nutritionWeekStatus");
  const cached = showCachedNutritionView(path, renderNutritionWeek);
  if (!cached && !preserve) {
    status.textContent = "Wochenübersicht wird geladen…";
    document.querySelector("#nutritionWeekTotals").replaceChildren();
    document.querySelector("#nutritionWeekDays").replaceChildren();
    document.querySelector("#nutritionWeekChart").replaceChildren();
    document.querySelector("#nutritionWeekChartSection").hidden = true;
    document.querySelector("#nutritionWeekPeriod").textContent = "";
    document.querySelector("#nutritionWeekDetails").hidden = true;
  }
  try {
    const week = await api(path);
    if (!isCurrentNutritionWeekLoad(sequence, generation, cacheEpoch, expectedRoute, expectedView)) return;
    renderNutritionWeek(week);
    rememberViewCache(path, week, cacheEpoch);
  } catch (error) {
    if (isCurrentNutritionWeekLoad(sequence, generation, cacheEpoch, expectedRoute, expectedView)) {
      status.textContent = cached
        ? `Gespeicherter Stand. Aktualisierung fehlgeschlagen: ${error.message}`
        : `Wochenübersicht konnte nicht geladen werden: ${error.message}`;
    }
    if (throwOnError) throw error;
  }
}

function isCurrentNutritionDayLoad(sequence, generation, cacheEpoch, dateInput, expectedRoute, expectedDate) {
  return sequence === nutritionLoadSequence
    && generation === state.sessionGeneration
    && cacheEpoch === viewCacheEpoch
    && (!expectedRoute || state.route === expectedRoute)
    && (!expectedDate || dateInput.value === expectedDate);
}

function renderNutritionDay(day) {
  document.querySelector("#nutritionDate").value = day.date;
  renderNutritionExpenditure(day.energy_expenditure, day.date);
  document.querySelector("#nutritionStatus").textContent = day.entry_count ? "" : "Noch keine Mahlzeiten erfasst. Das bedeutet nicht, dass du nichts gegessen hast.";
  const totals = document.querySelector("#nutritionTotals");
  totals.replaceChildren();
  appendNutritionTotals(totals, day);
  appendNutritionMacroNote(totals, Number(day.entries_without_macros) || 0);
  document.querySelector("#nutritionEntries").replaceChildren(...day.entries.map((item) => nutritionCard(item, false)));
}

function showNutritionDayLoadError(status, cached, error, dateInput, requestedDate) {
  if (cached) {
    status.textContent = `Gespeicherter Stand. Aktualisierung fehlgeschlagen: ${error.message}`;
    nutritionExpenditureSection().querySelector("#nutritionExpenditureStatus").textContent = `Gespeicherter Stand. Tagesverbrauch konnte nicht aktualisiert werden: ${error.message}`;
    return;
  }
  // The requested day stays in the date field so ← and → still have a day to move from.
  dateInput.value = requestedDate;
  const retry = h("button", { type: "button", className: "secondary-button" }, "Erneut laden");
  retry.addEventListener("click", () => void loadNutrition());
  status.textContent = `Ernährung konnte nicht geladen werden: ${error.message}`;
  status.append(h("br"), retry);
  clearNutritionExpenditure("");
  nutritionExpenditureSection().hidden = true;
}

async function loadNutrition({ preserve = false, expectedRoute = null, expectedDate = null, throwOnError = false } = {}) {
  const sequence = ++nutritionLoadSequence;
  const generation = state.sessionGeneration;
  if (state.route === "nutrition/body") return;
  if (state.route === "nutrition/week") return loadNutritionWeek(sequence, generation, preserve, expectedRoute, expectedDate, throwOnError);
  const dateInput = document.querySelector("#nutritionDate");
  const status = document.querySelector("#nutritionStatus");
  const path = dateInput.value ? `/api/nutrition/day?date=${encodeURIComponent(dateInput.value)}` : "/api/nutrition/day";
  // A start without a date asks for today, so its cached view is keyed by today.
  const cacheEpoch = viewCacheEpoch;
  const requestedDate = dateInput.value || todayIso();
  const cacheKey = `/api/nutrition/day?date=${encodeURIComponent(requestedDate)}`;
  const cached = showCachedNutritionView(cacheKey, renderNutritionDay);
  if (!cached && !preserve) {
    status.textContent = "Ernährung wird geladen…";
    clearNutritionExpenditure();
    document.querySelector("#nutritionEntries").replaceChildren();
    document.querySelector("#nutritionTotals").replaceChildren();
  }
  try {
    const day = await api(path);
    if (!isCurrentNutritionDayLoad(sequence, generation, cacheEpoch, dateInput, expectedRoute, expectedDate)) return;
    renderNutritionDay(day);
    rememberViewCache(`/api/nutrition/day?date=${encodeURIComponent(day.date)}`, day, cacheEpoch);
  } catch (error) {
    if (isCurrentNutritionDayLoad(sequence, generation, cacheEpoch, dateInput, expectedRoute, expectedDate)) {
      showNutritionDayLoadError(status, cached, error, dateInput, requestedDate);
      if (throwOnError) throw error;
    }
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

const nutritionRefresh = AppViewRefresh.create({
  api,
  waitForJob: (...args) => waitForSyncJob(...args),
  getRoute: () => state.route,
  getRequest: (route) => {
    const path = "/api/nutrition/refresh";
    if (route === "nutrition/products") return { path, body: { area: "products" } };
    if (route === "nutrition/body") return { path, body: { area: "body" } };
    if (route === "nutrition/week") return { path, body: { area: "week", days: nutritionHistoryPeriod === "twelveWeeks" ? 84 : 14 } };
    return { path, body: { area: "diary", date: document.querySelector("#nutritionDate").value || todayIso() } };
  },
  getViewKey: (route) => {
    if (route === "nutrition/week") return nutritionHistoryPeriod;
    if (route === "nutrition/diary") return document.querySelector("#nutritionDate").value;
    if (route === "nutrition/products") return document.querySelector("#nutritionProductQuery").value.trim();
    return null;
  },
  reload: (route, request) => {
    if (route === "nutrition/products") {
      const query = document.querySelector("#nutritionProductQuery").value.trim();
      return loadNutritionProducts(query, { background: true, throwOnError: true, refresh: true, expectedQuery: query });
    }
    if (route === "nutrition/body") return api("/api/performance").then((result) => {
      if (state.route !== route) return;
      state.data.performance = result.performance || result;
      renderBodyAnalysis(state.data.performance?.history?.body);
    });
    if (route === "nutrition/week") return loadNutrition({ preserve: true, expectedRoute: route, expectedDate: nutritionHistoryPeriod, throwOnError: true });
    return loadNutrition({ preserve: true, expectedRoute: route, expectedDate: document.querySelector("#nutritionDate").value, throwOnError: true });
  },
  button: document.querySelector("#nutritionRefreshButton"),
  status: document.querySelector("#nutritionRefreshStatus"),
});
document.querySelector("#nutritionRefreshButton").addEventListener("click", () => void nutritionRefresh());

function resetNutritionView() {
  ++nutritionLoadSequence;
  ++nutritionProductLoadSequence;
  nutritionLookupResultShown = false;
  nutritionProductSectionsOpen.favorites = nutritionProductSectionsOpen.all = false;
  nutritionProductSearchShown = "";
  nutritionProductSectionsBeforeSearch = null;
  stopNutritionBarcode();
  document.querySelector("#nutritionBarcodeDialog")?.close();
  document.querySelector("#nutritionProductUseDialog")?.close();
  nutritionProductForUse = null;
  document.querySelector("#nutritionDate").value = "";
  for (const id of ["nutritionWeekPeriod", "nutritionWeekStatus", "nutritionWeekTotals", "nutritionWeekDays", "nutritionWeekChart", "nutritionEntries", "nutritionTotals", "nutritionStatus", "nutritionProducts", "nutritionLookupResult", "nutritionProductStatus", "nutritionExpenditureTotals", "nutritionExpenditureStatus", "nutritionExpenditureDate"]) document.getElementById(id)?.replaceChildren();
  document.querySelector("#nutritionLookupResult").hidden = true;
  document.querySelector("#nutritionWeekChartSection").hidden = true;
  const editor = document.querySelector("#nutritionExtraction"); if (editor) { editor.replaceChildren(); editor.hidden = true; }
  const query = document.querySelector("#nutritionProductQuery"); if (query) query.value = "";
}

let nutritionBarcodeStream = null;
let nutritionBarcodeFrame = null;
let nutritionBarcodeDetector = null;
let nutritionBarcodeSession = 0;
let nutritionProductForUse = null;
let nutritionProductUseSequence = 0;
let nutritionProductLoadSequence = 0;
let nutritionLookupResultShown = false;

function nutritionProductValue(value) {
  return value == null || value === "" ? "" : String(value);
}

function nutritionDatabaseSource(source) {
  if (source === "Open Food Facts" || source === "open_food_facts") return "open_food_facts";
  if (source === "Yazio" || source === "yazio") return "yazio";
  return source || "packaging_label";
}

function normalizeNutritionProduct(product = {}) {
  const per100 = product.per_100 || {};
  const source = nutritionDatabaseSource(product.source);
  const normalized = {
    ...product,
    brand: product.brand || product.brands || "",
    kcal: product.kcal ?? per100.kcal ?? null,
    carbs_g: product.carbs_g ?? per100.carbs_g ?? null,
    protein_g: product.protein_g ?? per100.protein_g ?? null,
    fat_g: product.fat_g ?? per100.fat_g ?? null,
    sugar_g: product.sugar_g ?? per100.sugar_g ?? null,
    fiber_g: product.fiber_g ?? per100.fiber_g ?? null,
    salt_g: product.salt_g ?? per100.salt_g ?? null,
    confidence: product.confidence ?? product.extraction_confidence ?? null,
    source_url: product.source_url || "",
    source,
  };
  // A stored database entry is a product with an id of its own; only a live lookup hit has none.
  if (product.origin) return normalized;
  if (source === "open_food_facts" && String(product.id || "").startsWith("off:")) {
    normalized.external_id = normalized.external_id || product.id;
    const barcode = /^off:(\d{8,14})$/.exec(String(product.id));
    if (barcode && !normalized.barcode) normalized.barcode = barcode[1];
    delete normalized.id;
  }
  if (source === "yazio" && String(product.id || "").startsWith("yazio:")) {
    normalized.external_id = normalized.external_id || product.id;
    delete normalized.id;
  }
  return normalized;
}

function nutritionProductForm(product = {}) {
  const form = h("form", "nutrition-product-form");
  form.innerHTML = `<input name="id" type="hidden"><input name="source" type="hidden"><input name="source_url" type="hidden"><input name="external_id" type="hidden"><input name="provenance" type="hidden"><input name="warnings" type="hidden"><label>Marke<input name="brand" maxlength="120"></label><label>EAN/GTIN<input name="barcode" inputmode="numeric" pattern="[0-9]{8,14}" maxlength="14"></label><div class="nutrition-product-grid"><label>Name<input name="name" required maxlength="160"></label><label>kcal<input name="kcal" type="number" min="0" step="any"></label><label>Kohlenhydrate (g)<input name="carbs_g" type="number" min="0" step="any"></label><label>Protein (g)<input name="protein_g" type="number" min="0" step="any"></label><label>Fett (g)<input name="fat_g" type="number" min="0" step="any"></label><label>Bezugsmenge<input name="basis_amount" type="number" min="0.1" step="0.1" value="100"></label><label>Einheit<select name="basis_unit"><option value="g">pro 100 g</option><option value="ml">pro 100 ml</option><option value="portion">pro Portion</option></select></label></div><p class="fine-print" data-extraction-confidence></p><ul class="nutrition-warning-checklist" data-extraction-warnings aria-label="Hinweise zur Prüfung" hidden></ul><p class="fine-print">Leere Nährwerte bleiben unbekannt. Bitte prüfe jede erkannte Zahl vor dem Speichern.</p><div class="nutrition-actions"><button type="submit" class="push-button">Produkt lokal speichern</button><button type="button" class="secondary-button" data-product-cancel>Abbrechen</button></div>`;
  populateNutritionProductFields(form, product);
  form.elements.source.value = product.source || "packaging_label";
  form.append(h("input", { name: "confidence", type: "hidden", value: nutritionProductValue(product.confidence) }));
  form.elements.basis_amount.required = true;
  form.elements.basis_unit.required = true;
  setNutritionProductBasis(form, product);
  setNutritionProductMetadata(form, product);
  setNutritionProductConfidence(form, product);
  if (product.origin && nutritionIsDatabaseProduct(product)) lockNutritionDatabaseFields(form);
  return form;
}

// A database owns name, brand, EAN and basis of its entry: shown, not editable.
function lockNutritionDatabaseFields(form) {
  form.dataset.database = "true";
  for (const name of ["name", "brand", "barcode", "basis_amount", "basis_unit"]) form.elements[name].disabled = true;
  // The values come from the database, not from a label photo.
  for (const hint of form.querySelectorAll("p.fine-print")) hint.hidden = true;
  form.querySelector('button[type="submit"]').textContent = "Nährwerte speichern";
}

function populateNutritionProductFields(form, product) {
  for (const [key, value] of Object.entries(product)) {
    const field = form.elements.namedItem(key);
    if (field) field.value = nutritionProductValue(value);
  }
  const grid = form.querySelector(".nutrition-product-grid");
  for (const [key, label] of [["sugar_g", "Zucker (g)"], ["fiber_g", "Ballaststoffe (g)"], ["salt_g", "Salz (g)"]]) {
    grid.append(h("label", null, label, h("input", { name: key, type: "number", min: "0", step: "any", value: nutritionProductValue(product[key]) })));
  }
}

function setNutritionProductBasis(form, product) {
  if (!product.basis_amount) form.elements.basis_amount.value = "";
  if (product.basis_unit) return;
  form.elements.basis_unit.prepend(h("option", { value: "", selected: true, disabled: true }, "Bezugsmenge auswählen"));
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
  const confidenceLine = form.querySelector("[data-extraction-confidence]");
  confidenceLine.textContent = Number.isFinite(confidence) ? `Erkennungssicherheit: ${Math.round(confidence * 100)} %. ${warning}` : warning;
  const checklist = form.querySelector("[data-extraction-warnings]");
  const warnings = Array.isArray(product.warnings) ? product.warnings.map((text) => String(text ?? "").trim()).filter(Boolean) : [];
  checklist.replaceChildren(...warnings.map((text) => h("li", null, text)));
  checklist.hidden = warnings.length === 0;
  for (const [field, score] of Object.entries(product.field_confidence || {})) {
    const input = form.elements.namedItem(field);
    if (input && Number(score) < 0.65) { input.classList.add("nutrition-low-confidence"); input.title = "Unsichere Fotoerkennung; bitte am Etikett prüfen."; }
  }
}

function nutritionProductPayload(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  const numbers = Object.keys(NUTRITION_FIELD_NAMES);
  if (form.dataset.database === "true") return Object.fromEntries([["id", data.id], ...numbers.map((key) => [key, data[key] === "" ? null : Number(data[key])])]);
  const source = data.source || "packaging_label";
  let provenance;
  try { provenance = JSON.parse(data.provenance || "{}"); } catch { provenance = {}; }
  const payload = { ...data, source, provenance: { ...(provenance && typeof provenance === "object" ? provenance : {}), kind: source, confirmed: true } };
  try { payload.warnings = JSON.parse(data.warnings || "[]"); } catch { payload.warnings = []; }
  for (const key of [...numbers, "basis_amount", "confidence"]) payload[key] = data[key] === "" ? null : Number(data[key]);
  return payload;
}

const NUTRITION_FIELD_NAMES = { kcal: "Energie", carbs_g: "Kohlenhydrate", protein_g: "Eiweiß", fat_g: "Fett", sugar_g: "Zucker", fiber_g: "Ballaststoffe", salt_g: "Salz" };
const NUTRITION_PRODUCT_SECTIONS = [["favorites", "Favoriten"], ["all", "Alle Produkte"]];
// Both sections start collapsed whenever the page is opened (#2267).
const nutritionProductSectionsOpen = { favorites: false, all: false };

function nutritionIsDatabaseProduct(product) {
  return product.origin ? product.origin !== "own" : product.local === false;
}

function nutritionMissingFields(product) {
  const keys = Array.isArray(product.missing_fields) ? product.missing_fields : Object.keys(NUTRITION_FIELD_NAMES).filter((key) => product[key] == null);
  return keys.map((key) => NUTRITION_FIELD_NAMES[key] || key);
}

// A fetch time as the athlete's local date, "01.10.2026".
function nutritionProductDate(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" }) : "";
}

const NUTRITION_SOURCE_NAMES = { packaging_label: "Verpackungsangabe", manual: "manuell", open_food_facts: "Open Food Facts", yazio: "Yazio", bls: "BLS", fddb_export: "FDDB" };

function nutritionOriginText(product) {
  if (!nutritionIsDatabaseProduct(product)) return ["eigen", NUTRITION_SOURCE_NAMES[product.source]].filter(Boolean).join(" · ");
  const date = nutritionProductDate(product.fetched_at || product.stored_at);
  return date ? `Datenbank · Stand ${date}` : "Datenbank";
}

function nutritionIncompleteMark(label, text) {
  const mark = h("span", { className: "nutrition-incomplete", "aria-label": label }, text);
  mark.setAttribute("role", "img");
  return mark;
}

function reloadNutritionProducts(options = {}) {
  return loadNutritionProducts(document.querySelector("#nutritionProductQuery").value.trim(), options);
}

function showNutritionProductError(prefix, error) {
  document.querySelector("#nutritionProductStatus").textContent = `${prefix}: ${error.message}`;
}

async function refreshNutritionProduct(product, button) {
  button.disabled = true;
  const status = document.querySelector("#nutritionProductStatus");
  const generation = state.sessionGeneration;
  try {
    const result = await api("/api/nutrition/products/database/refresh", { method: "POST", body: JSON.stringify({ id: product.id }) });
    if (generation !== state.sessionGeneration) return;
    await reloadNutritionProducts({ refresh: true });
    if (generation !== state.sessionGeneration) return;
    showNutritionReceipt(status, [`„${product.name}“ aktualisiert.`, result.notice || result.food?.notice].filter(Boolean).join(" "), result.change, () => reloadNutritionProducts({ refresh: true }));
  } catch (error) {
    if (generation !== state.sessionGeneration) return;
    status.textContent = error.reason === "nutrition_product_barcode_missing"
      ? "Für Aktualisieren wird eine EAN gebraucht. Unter Bearbeiten eintragen."
      : `Eintrag konnte nicht aktualisiert werden: ${error.message}`;
  }
  button.disabled = false;
}

async function deleteNutritionProduct(product) {
  const database = nutritionIsDatabaseProduct(product);
  const question = database ? `Eintrag „${product.name}“ aus der Datenbank entfernen? Eigene Produkte bleiben erhalten.` : `Produkt „${product.name}“ wirklich löschen?`;
  if (!await requestConfirmation(question)) return;
  const generation = state.sessionGeneration;
  try {
    const result = await api(database ? "/api/nutrition/products/database/delete" : "/api/nutrition/products/archive", { method: "POST", body: JSON.stringify({ id: product.id, confirmed: true }) });
    if (generation !== state.sessionGeneration) return;
    await reloadNutritionProducts();
    if (generation !== state.sessionGeneration) return;
    showNutritionReceipt(document.querySelector("#nutritionProductStatus"), database ? `Eintrag „${product.name}“ aus der Datenbank entfernt.` : `Produkt „${product.name}“ gelöscht.`, result.change, () => reloadNutritionProducts());
  } catch (error) { if (generation === state.sessionGeneration) showNutritionProductError(database ? "Eintrag konnte nicht entfernt werden" : "Produkt konnte nicht gelöscht werden", error); }
}

function appendNutritionProductActions(card, product, local) {
  if (!local || product.local === false) {
    const button = h("button", { type: "button", className: "secondary-button" }, "Lokal speichern");
    button.addEventListener("click", () => saveNutritionProduct(product)); card.append(button);
  } else if (product.id) {
    const actions = h("div", "nutrition-actions");
    for (const [label, primary, run] of [
      ["Verwenden", true, () => useNutritionProduct(product)],
      ["Bearbeiten", false, () => saveNutritionProduct(product)],
      ["Aktualisieren", false, (button) => refreshNutritionProduct(product, button)],
      ["Löschen", false, () => deleteNutritionProduct(product)],
    ]) {
      const button = h("button", { type: "button", className: primary ? "push-button" : "secondary-button" }, label);
      button.addEventListener("click", () => run(button)); actions.append(button);
      // Without a known unit an amount cannot be counted against the values.
      if (label === "Verwenden" && !product.basis_unit) { button.disabled = true; button.title = "Bezugsmenge unbekannt"; }
    }
    card.append(actions);
  }
}

function nutritionFavoriteButton(product) {
  const favorite = Boolean(product.favorite);
  const button = h("button", { type: "button", className: "nutrition-favorite", "aria-pressed": String(favorite), "aria-label": `${favorite ? "Favorit entfernen" : "Als Favorit markieren"}: ${product.name}` }, favorite ? "★" : "☆");
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await api("/api/nutrition/products/favorite", { method: "POST", body: JSON.stringify({ id: product.id, favorite: !favorite }) });
      await reloadNutritionProducts({ refresh: true });
    } catch (error) {
      showNutritionProductError("Favorit konnte nicht geändert werden", error);
      button.disabled = false;
    }
  });
  return button;
}

function nutritionProductSection(key, title, products, searching) {
  const section = h("details", { className: "nutrition-product-section", dataset: { section: key } });
  // A new search opens the sections with hits once; later toggles are kept.
  if (searching) nutritionProductSectionsOpen[key] = products.length > 0;
  section.open = nutritionProductSectionsOpen[key];
  section.addEventListener("toggle", () => { nutritionProductSectionsOpen[key] = section.open; });
  const incomplete = products.filter((product) => nutritionMissingFields(product).length).length;
  section.append(
    h("summary", null, `${title} (${products.length})`, incomplete ? [" ", nutritionIncompleteMark(`${incomplete} unvollständig`, `⚠ ${incomplete}`)] : null),
    h("div", "nutrition-list", products.map((product) => nutritionProductCard(product, true))));
  return section;
}

function nutritionProductCard(product, local) {
  const kcalLabel = product.kcal == null ? "kcal unbekannt" : `${product.kcal} kcal`;
  const missing = nutritionMissingFields(product);
  const card = h("article", "nutrition-card nutrition-product-card",
    h("div", "nutrition-product-head",
      h("h3", null, [product.brand, product.name].filter(Boolean).join(" · ") || "Unbenanntes Produkt"),
      local && product.id && product.local !== false ? nutritionFavoriteButton(product) : null),
    h("p", null, `${kcalLabel} · KH ${product.carbs_g ?? "–"} g · Protein ${product.protein_g ?? "–"} g · Fett ${product.fat_g ?? "–"} g`),
    h("div", "nutrition-product-marks",
      h("span", "nutrition-origin", nutritionOriginText(product)),
      missing.length ? nutritionIncompleteMark(`Unvollständig, es fehlen: ${missing.join(", ")}`, `⚠ fehlt: ${missing.join(", ")}`) : null),
    h("small", null, [product.barcode ? `EAN ${product.barcode}` : "", product.basis_amount && product.basis_unit ? `Basis: ${product.basis_amount} ${product.basis_unit}` : "Bezugsmenge unbekannt"].filter(Boolean).join(" · ")));
  appendNutritionProductActions(card, product, local);
  return card;
}

let nutritionProductSearchShown = "";
// What was open before a search; clearing the search restores it.
let nutritionProductSectionsBeforeSearch = null;

function renderNutritionProducts(products, { local = true, targetId = "#nutritionProducts", search = "" } = {}) {
  const target = document.querySelector(targetId);
  if (!target) return;
  target.replaceChildren();
  if (!products?.length) { target.textContent = "Keine Produkte gefunden."; return; }
  const items = products.map(normalizeNutritionProduct);
  if (!local || targetId !== "#nutritionProducts") { target.append(...items.map((product) => nutritionProductCard(product, local))); return; }
  const newSearch = Boolean(search) && search !== nutritionProductSearchShown;
  if (newSearch && !nutritionProductSearchShown) nutritionProductSectionsBeforeSearch = { ...nutritionProductSectionsOpen };
  if (!search && nutritionProductSectionsBeforeSearch) { Object.assign(nutritionProductSectionsOpen, nutritionProductSectionsBeforeSearch); nutritionProductSectionsBeforeSearch = null; }
  nutritionProductSearchShown = search || "";
  target.append(...NUTRITION_PRODUCT_SECTIONS.map(([key, title]) => nutritionProductSection(key, title, key === "favorites" ? items.filter((product) => product.favorite) : items, newSearch)));
}

async function useNutritionProduct(product) {
  const unit = nutritionProductUnit(product);
  nutritionProductForUse = product;
  const useSequence = ++nutritionProductUseSequence;
  const dialog = document.querySelector("#nutritionProductUseDialog");
  document.querySelector("#nutritionProductUseName").textContent = product.name || "Lokales Produkt";
  document.querySelector("#nutritionProductUseUnit").textContent = `(in ${unit})`;
  const amount = document.querySelector("#nutritionProductUseAmount"); amount.value = product.basis_amount || 100;
  const select = document.querySelector("#nutritionProductUseMeal");
  const addButton = document.querySelector("#nutritionProductUseAdd");
  const status = document.querySelector("#nutritionProductUseStatus");
  select.replaceChildren(h("option", { value: "" }, "Neuer Snack")); addButton.disabled = true; status.textContent = "";
  dialog.showModal();
  const generation = state.sessionGeneration;
  try {
    const day = await api(`/api/nutrition/day?date=${encodeURIComponent(document.querySelector("#nutritionDate").value || todayIso())}`);
    if (generation !== state.sessionGeneration || useSequence !== nutritionProductUseSequence) return;
    for (const meal of day.entries || []) {
      select.append(h("option", { value: meal.id }, [nutritionMealTitle(meal), String(meal.description || "").slice(0, 40)].filter(Boolean).join(" · ")));
    }
  } catch (error) {
    if (generation === state.sessionGeneration && useSequence === nutritionProductUseSequence) status.textContent = `Mahlzeiten konnten nicht geladen werden: ${error.message}`;
  } finally {
    if (generation === state.sessionGeneration && useSequence === nutritionProductUseSequence) addButton.disabled = false;
  }
}

function nutritionProductUnit(product = {}) {
  const unit = String(product.basis_unit || "g").toLowerCase();
  return ["g", "ml", "portion"].includes(unit) ? unit : "g";
}

function nutritionProductUseAmount() {
  const product = nutritionProductForUse;
  const form = document.querySelector("#nutritionProductUseForm");
  if (!product || !form.reportValidity()) return null;
  return { product, unit: nutritionProductUnit(product), amount: document.querySelector("#nutritionProductUseAmount").value };
}

function closeNutritionProductUse() {
  document.querySelector("#nutritionProductUseDialog")?.close();
  nutritionProductForUse = null;
}

function addNutritionProductToCoachDraft() {
  const use = nutritionProductUseAmount();
  const input = document.querySelector("#messageInput");
  if (!use || !input) return;
  const { product, unit, amount } = use;
  const draft = input.value.trimEnd();
  input.value = draft
    ? `${draft}\nDazu ${amount} ${unit} (Produkt-ID: ${product.id}).`
    : `Erfasse ${amount} ${unit} als Mahlzeit (Produkt-ID: ${product.id}).`;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  state.chatDraftDirty = true;
  closeNutritionProductUse();
  void AppRouter.navigate("coach", { historyMode: "push" });
  jumpToLatestMessages();
}

async function addNutritionProductToMeal() {
  const use = nutritionProductUseAmount();
  const mealId = document.querySelector("#nutritionProductUseMeal").value;
  if (!use) return;
  const generation = state.sessionGeneration;
  const addButton = document.querySelector("#nutritionProductUseAdd");
  addButton.disabled = true;
  try {
    const body = mealId
      ? { id: mealId, product_id: use.product.id, amount: Number(use.amount), unit: use.unit }
      : { product_id: use.product.id, amount: Number(use.amount), unit: use.unit, meal_type: "snack", meal_date: document.querySelector("#nutritionDate").value || todayIso(), source: "manual" };
    const result = await api(mealId ? "/api/nutrition/entry/add-product" : "/api/nutrition/entry", { method: "POST", body: JSON.stringify(body) });
    if (generation !== state.sessionGeneration) return;
    closeNutritionProductUse();
    showNutritionReceipt(document.querySelector("#nutritionProductStatus"), `„${use.product.name}“ ${mealId ? "zur Mahlzeit ergänzt" : "als Snack erfasst"}.`, result.change);
  } catch (error) {
    if (generation !== state.sessionGeneration) return;
    document.querySelector("#nutritionProductUseStatus").textContent = `Produkt konnte nicht erfasst werden: ${error.message}`;
    addButton.disabled = false;
  }
}

function isCurrentNutritionProductLoad(sequence, generation, expectedQuery) {
  return sequence === nutritionProductLoadSequence
    && generation === state.sessionGeneration
    && (expectedQuery === null || document.querySelector("#nutritionProductQuery").value.trim() === expectedQuery);
}

function prepareNutritionProductLookup(preserveLookup) {
  if (preserveLookup) return;
  nutritionLookupResultShown = false;
  const lookup = document.querySelector("#nutritionLookupResult");
  if (lookup) { lookup.hidden = true; lookup.replaceChildren(); }
}

function showNutritionProductLoadError(preserveLookup, sequence, generation, expectedQuery, error) {
  if (!preserveLookup && isCurrentNutritionProductLoad(sequence, generation, expectedQuery)) {
    document.querySelector("#nutritionProductStatus").textContent = `Produktsuche fehlgeschlagen: ${error.message}`;
  }
}

async function loadNutritionProducts(query = "", { background = false, throwOnError = false, refresh = false, expectedQuery = null } = {}) {
  if (background && nutritionLookupResultShown && !refresh) return;
  const preserveLookup = refresh && nutritionLookupResultShown;
  prepareNutritionProductLookup(preserveLookup);
  const sequence = ++nutritionProductLoadSequence;
  const generation = state.sessionGeneration;
  const status = document.querySelector("#nutritionProductStatus");
  try {
    if (!preserveLookup) status.textContent = "Produkte werden gesucht …";
    const search = query ? "&q=" + encodeURIComponent(query) : "";
    const result = await api(`/api/nutrition/products?scope=all${search}`);
    if (!isCurrentNutritionProductLoad(sequence, generation, expectedQuery)) return;
    renderNutritionProducts(result.products || [], { search: query });
    if (!preserveLookup) status.textContent = result.products?.length ? "" : "Keine Produkte gefunden.";
  } catch (error) {
    showNutritionProductLoadError(preserveLookup, sequence, generation, expectedQuery, error);
    if (throwOnError) throw error;
  }
}

async function submitNutritionProductForm(form) {
  const generation = state.sessionGeneration;
  const editor = document.querySelector("#nutritionExtraction");
  const status = document.querySelector("#nutritionProductStatus");
  try {
    const payload = nutritionProductPayload(form);
    const saved = await api("/api/nutrition/products", { method: payload.id ? "PUT" : "POST", body: JSON.stringify({ ...payload, confirmed: true }) });
    if (generation !== state.sessionGeneration) return;
    // The list is read again with the search the athlete is in.
    editor.hidden = true; editor.replaceChildren(); await reloadNutritionProducts();
    const name = saved.product?.name || "Produkt";
    const message = form.dataset.database === "true" ? `Nährwerte von „${name}“ gespeichert.` : `Produkt „${name}“ lokal gespeichert.`;
    if (generation === state.sessionGeneration) showNutritionReceipt(status, message, saved.change, () => reloadNutritionProducts());
  } catch (error) { if (generation === state.sessionGeneration) status.textContent = `Produkt konnte nicht gespeichert werden: ${error.message}`; }
}

async function saveNutritionProduct(product) {
  if (product instanceof HTMLFormElement) return submitNutritionProductForm(product);
  const editor = document.querySelector("#nutritionExtraction");
  const form = nutritionProductForm(normalizeNutritionProduct(product));
  editor.replaceChildren(); editor.append(form); editor.hidden = false;
  form.scrollIntoView({ block: "nearest" });
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
    ++nutritionProductLoadSequence;
    nutritionLookupResultShown = true;
    const product = result.product || result.foods?.[0] || result.products?.[0] || null;
    const isLocal = result.local !== false && result.source !== "open_food_facts";
    const editor = document.querySelector("#nutritionExtraction");
    if (editor) { editor.replaceChildren(); editor.hidden = true; }
    const lookup = document.querySelector("#nutritionLookupResult");
    if (lookup) lookup.hidden = false;
    renderNutritionProducts(product ? [{ ...product, local: isLocal }] : [], { local: isLocal, targetId: "#nutritionLookupResult" });
    document.querySelector("#nutritionProductStatus").textContent = isLocal ? "Lokales Produkt gefunden." : "Online-Treffer gefunden. Prüfe ihn und speichere ihn lokal.";
    if (product && !isLocal) await saveNutritionProduct(normalizeNutritionProduct({ ...product, barcode: product.barcode || clean, source: result.source || product.source || "open_food_facts" }));
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
document.querySelector("#nutritionProductUseDialog")?.addEventListener("close", () => { nutritionProductForUse = null; ++nutritionProductUseSequence; });
document.querySelector("#nutritionProductUseForm")?.addEventListener("submit", (event) => { event.preventDefault(); void addNutritionProductToMeal(); });
document.querySelector("#nutritionProductUseCoach")?.addEventListener("click", addNutritionProductToCoachDraft);
function handleNutritionRoute(route) {
  if (route === "nutrition/products") return;
  nutritionProductSectionsOpen.favorites = nutritionProductSectionsOpen.all = false;
  nutritionProductSearchShown = "";
  nutritionProductSectionsBeforeSearch = null;
  const query = document.querySelector("#nutritionProductQuery"); if (query) query.value = "";
  stopNutritionBarcode(); document.querySelector("#nutritionBarcodeDialog")?.close();
}
globalThis.AppNutrition = Object.freeze({ handleRoute: handleNutritionRoute });
globalThis.addEventListener("pagehide", stopNutritionBarcode);
document.addEventListener("visibilitychange", () => { if (document.hidden) stopNutritionBarcode(); });
