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
  const names = { "nutrition/diary": "Tagebuch", "nutrition/week": "Verlauf", "nutrition/body": "Body", "nutrition/products": "Produkte" };
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
  if (basis?.kind === "composite") return "";
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
  const mealTime = item.logged_time_known === false ? "" : String(item.logged_at).split("T")[1]?.slice(0, 5) || "";
  const mealTitle = mealTime ? `${mealTime} · ${mealLabel}` : mealLabel;
  title.textContent = template ? item.name : mealTitle;
  const description = document.createElement("p");
  description.textContent = item.description;
  const values = document.createElement("p");
  values.textContent = `${nutritionNumber(item.kcal)} kcal · KH ${nutritionNumber(item.carbs_g)} g · Protein ${nutritionNumber(item.protein_g)} g · Fett ${nutritionNumber(item.fat_g)} g${template ? " / Portion" : ""}`;
  const source = document.createElement("small");
  const sourceLabels = { coach: "Coach-Schätzung", photo: "Foto-Schätzung", voice: "Sprach-Schätzung", manual: "Manuelle Angabe" };
  const sourceLabel = sourceLabels[item.source] || "Erfasst";
  const syncLabel = item.sync_state === "synced" ? " · Synchronisiert" : " · Lokal";
  const basisLabel = nutritionBasisLabel(item.nutrition_basis, { template, syncLabel }, sourceLabel);
  if (basisLabel) source.textContent = basisLabel + (template ? "" : syncLabel);
  card.append(title, description, values);
  if (source.textContent) card.append(source);
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

  const formatKcal = (rawValue) => {
    const value = rawValue == null || rawValue === "" ? null : Number(rawValue);
    return value != null && Number.isFinite(value)
      ? `${AppFormat.number(value, { digits: 0 })} kcal`
      : "Nicht verfügbar";
  };
  const totalTile = document.createElement("div");
  totalTile.className = "nutrition-total";
  totalTile.style.gridColumn = "1 / -1";
  const totalValue = document.createElement("strong");
  totalValue.textContent = formatKcal(expenditure?.total_kcal);
  const totalCaption = document.createElement("span");
  totalCaption.textContent = expenditure?.provisional ? "Tagesverbrauch (vorläufig)" : "Tagesverbrauch";
  totalTile.append(totalValue, totalCaption);

  const componentTile = (rawValue, caption) => {
    const tile = document.createElement("div");
    tile.className = "nutrition-total";
    const value = document.createElement("strong");
    value.textContent = formatKcal(rawValue);
    const label = document.createElement("span");
    label.textContent = caption;
    tile.append(value, label);
    return tile;
  };
  const projected = expenditure?.projected_total_kcal;
  const hasProjection = projected != null && Number.isFinite(Number(projected));
  const projectionTile = hasProjection ? componentTile(projected, "Prognose Tagesverbrauch (abgeleitet)") : null;
  if (projectionTile) projectionTile.style.gridColumn = "1 / -1";
  totals.replaceChildren(
    totalTile,
    ...(projectionTile ? [projectionTile] : []),
    componentTile(expenditure?.active_kcal, "Aktivkalorien"),
    componentTile(expenditure?.resting_kcal, expenditure?.provisional ? "Grundumsatz (vorläufig)" : "Grundumsatz"),
  );

  const syncedAt = nutritionExpenditureTimestamp(expenditure?.synced_at);
  const fetchedAt = nutritionExpenditureTimestamp(expenditure?.fetched_at);
  date.textContent = "";
  if (syncedAt) date.textContent = `Sync: ${syncedAt}`;
  else if (fetchedAt) date.textContent = `Abgerufen: ${fetchedAt}`;
  if (projectionTile) {
    projectionTile.title = `Grundumsatz vom ${nutritionExpenditureDate(expenditure.projection_reference_date)} (${formatKcal(expenditure.projection_resting_kcal)}) + bisherige Aktivkalorien (${formatKcal(expenditure.active_kcal)}), eigene Schätzung`;
  }
}

function appendNutritionTotals(totals, day) {
  // Empty days report zero totals, which are unknown, so the tiles stay at "–".
  const hasEntries = Number(day.entry_count) > 0;
  for (const [label, key, unit] of [["Kalorien", "kcal", "kcal"], ["Kohlenhydrate", "carbs_g", "g"], ["Protein", "protein_g", "g"], ["Fett", "fat_g", "g"], ["Zucker", "sugar_g", "g"], ["Salz", "salt_g", "g"]]) {
    totals.append(nutritionTotalTile(label, key, unit, day, hasEntries));
  }
}

function nutritionTotalTile(label, key, unit, day, hasEntries) {
  const tile = document.createElement("div");
  tile.className = "nutrition-total";
  const value = document.createElement("strong");
  const complete = hasEntries ? day[`total_${key}`] : null;
  // A partial sum of known values is shown only with an explicit incompleteness label.
  const total = hasEntries ? (complete ?? day.known_macro_totals?.[key] ?? day.known_intake_totals?.[key]) : null;
  const totalText = total != null ? nutritionNumber(total) : "–";
  value.textContent = `${totalText} ${unit}`;
  const caption = document.createElement("span");
  caption.textContent = label + (complete == null && total != null ? " · unvollständig" : "");
  tile.append(value, caption);
  return tile;
}

function appendNutritionMacroNote(totals, entriesWithoutMacros) {
  if (entriesWithoutMacros > 0) {
    const note = document.createElement("p");
    note.className = "nutrition-total-note";
    note.textContent = entriesWithoutMacros === 1 ? "1 Eintrag ohne vollständige Makros" : `${entriesWithoutMacros} Einträge ohne vollständige Makros`;
    totals.append(note);
  }
}

function nutritionWeekValue(value, unit, signed = false) {
  if (value == null) return "Nicht verfügbar";
  const prefix = signed && value > 0 ? "+" : "";
  const suffix = unit ? ` ${unit}` : "";  return `${prefix}${AppFormat.number(value, { digits: unit === "g" ? 1 : 0 })}${suffix}`;}

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

function renderNutritionWeek(week) {
  const dayCount = week.days.length;
  document.querySelector("#nutritionWeekHeading").textContent = dayCount === 84 ? "Letzte 12 Wochen" : `Letzte ${dayCount} Tage`;
  document.querySelector("#nutritionWeekPeriod").textContent = `${nutritionExpenditureDate(week.start_date)} – ${nutritionExpenditureDate(week.end_date)}`;
  const totals = document.querySelector("#nutritionWeekTotals");
  const balance = week.balance_kcal;
  let balanceLabel = "Bilanz";  if (balance != null) {    balanceLabel = "Ausgeglichene Bilanz";    if (balance > 0) balanceLabel = "Kalorienüberschuss";    if (balance < 0) balanceLabel = "Kaloriendefizit";  }  if (balance != null && week.balance_days < dayCount) balanceLabel = "Erfasste Teilbilanz";
  const items = [[balanceLabel, balance, "kcal", week.balance_days, true],
    ...[["Ø Aufnahme", "intake_kcal", "kcal"], ["Ø Verbrauch", "expenditure_kcal", "kcal"], ["Ø Kohlenhydrate", "carbs_g", "g"], ["Ø Protein", "protein_g", "g"], ["Ø Fett", "fat_g", "g"], ["Ø Zucker", "sugar_g", "g"], ["Ø Salz", "salt_g", "g"]].map(([label, key, unit]) => [label, week.averages[key].value, unit, week.averages[key].days, false])];
  totals.replaceChildren(...items.map(([label, value, unit, days, isBalance]) => {
    const tile = document.createElement("div"); tile.className = "nutrition-total";
    if (isBalance) tile.style.gridColumn = "1 / -1";
    const number = document.createElement("strong"); number.textContent = nutritionWeekValue(value, unit, isBalance);
    const caption = document.createElement("span"); caption.textContent = label;
    const coverage = document.createElement("small"); coverage.textContent = `${days} von ${dayCount} Tagen${isBalance && days < dayCount ? " · Teilbilanz" : ""}`;
    tile.append(number, caption, coverage); return tile;
  }));
  document.querySelector("#nutritionWeekStatus").textContent = week.balance_days === dayCount ? `Alle ${dayCount} Tage auswertbar.` : `${week.balance_days} von ${dayCount} Tagen mit Aufnahme und Gesamtverbrauch auswertbar. Für die übrigen Tage bleibt die Bilanz offen.`;
  const chartDays = nutritionChartDays(week.days);
  document.querySelector("#nutritionWeekChartHeading").textContent = dayCount === 84 ? "Wochendurchschnitte" : "Tagesverlauf";
  const scale = Math.max(1, ...chartDays.flatMap((day) => [day.intake_kcal, day.expenditure_kcal].filter((value) => Number.isFinite(value) && value >= 0)));
  document.querySelector("#nutritionWeekChart").replaceChildren(...chartDays.map((day) => {
    const row = document.createElement("div"); row.className = "nutrition-week-chart-day";
    const date = document.createElement("strong"); date.textContent = nutritionExpenditureDate(day.date).slice(0, 5);
    if (day.end_date) date.setAttribute("aria-label", `${nutritionExpenditureDate(day.date)} bis ${nutritionExpenditureDate(day.end_date)}`);
    row.append(date);
    for (const [key, label, kind] of [["intake_kcal", "Aufnahme", "intake"], ["expenditure_kcal", "Verbrauch", "expenditure"]]) {
      const value = day[key];
      const series = document.createElement("div"); series.className = `nutrition-week-chart-series is-${kind}`;
      const track = document.createElement("span"); track.className = "nutrition-week-chart-track";
      if (Number.isFinite(value) && value >= 0) {
        const bar = document.createElement("span"); bar.className = "nutrition-week-chart-bar";
        bar.style.width = `${value / scale * 100}%`;
        track.append(bar);
      } else track.classList.add("is-missing");
      const amount = document.createElement("span"); amount.textContent = value == null ? "–" : `${nutritionWeekValue(value, "kcal")}`;
      series.setAttribute("aria-label", `${label}: ${amount.textContent}${value == null ? " (keine Daten)" : ""}`);
      if (day.end_date) {
        const coverage = document.createElement("small");
        coverage.textContent = `${day[key + "_days"]} von 7 Tagen`;
        series.setAttribute("aria-label", `${label}: ${amount.textContent}, ${coverage.textContent}`);
        amount.append(document.createElement("br"), coverage);
      }
      series.append(track, amount); row.append(series);
    }
    return row;
  }));
  document.querySelector("#nutritionWeekChartSection").hidden = false;
  document.querySelector("#nutritionWeekDays").replaceChildren(...week.days.map((day) => {
    const row = document.createElement("tr");
    const date = document.createElement("th"); date.scope = "row"; date.textContent = nutritionExpenditureDate(day.date).slice(0, 5); row.append(date);
    for (const key of ["intake_kcal", "expenditure_kcal", "balance_kcal"]) {
      const cell = document.createElement("td"); cell.textContent = day[key] == null ? "–" : nutritionWeekValue(day[key], "", key === "balance_kcal"); row.append(cell);
    }
    return row;
  }));
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
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "secondary-button";
  retry.textContent = "Erneut laden";
  retry.addEventListener("click", () => void loadNutrition());
  status.textContent = `Ernährung konnte nicht geladen werden: ${error.message}`;
  status.append(document.createElement("br"), retry);
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
let nutritionProductLoadSequence = 0;
let nutritionLookupResultShown = false;

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
  form.innerHTML = `<input name="id" type="hidden"><input name="source" type="hidden"><input name="source_url" type="hidden"><input name="external_id" type="hidden"><input name="provenance" type="hidden"><input name="warnings" type="hidden"><label>Marke<input name="brand" maxlength="120"></label><label>EAN/GTIN<input name="barcode" inputmode="numeric" pattern="[0-9]{8,14}" maxlength="14"></label><div class="nutrition-product-grid"><label>Name<input name="name" required maxlength="160"></label><label>kcal<input name="kcal" type="number" min="0" step="0.1"></label><label>Kohlenhydrate (g)<input name="carbs_g" type="number" min="0" step="0.1"></label><label>Protein (g)<input name="protein_g" type="number" min="0" step="0.1"></label><label>Fett (g)<input name="fat_g" type="number" min="0" step="0.1"></label><label>Bezugsmenge<input name="basis_amount" type="number" min="0.1" step="0.1" value="100"></label><label>Einheit<select name="basis_unit"><option value="g">pro 100 g</option><option value="ml">pro 100 ml</option><option value="portion">pro Portion</option></select></label></div><p class="fine-print" data-extraction-confidence></p><ul class="nutrition-warning-checklist" data-extraction-warnings aria-label="Hinweise zur Prüfung" hidden></ul><p class="fine-print">Leere Nährwerte bleiben unbekannt. Bitte prüfe jede erkannte Zahl vor dem Speichern.</p><div class="nutrition-actions"><button type="submit" class="push-button">Produkt lokal speichern</button><button type="button" class="secondary-button" data-product-cancel>Abbrechen</button></div>`;
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
  const confidenceLine = form.querySelector("[data-extraction-confidence]");
  confidenceLine.textContent = Number.isFinite(confidence) ? `Erkennungssicherheit: ${Math.round(confidence * 100)} %. ${warning}` : warning;
  const checklist = form.querySelector("[data-extraction-warnings]");
  const warnings = Array.isArray(product.warnings) ? product.warnings.map((text) => String(text ?? "").trim()).filter(Boolean) : [];
  checklist.replaceChildren(...warnings.map((text) => { const row = document.createElement("li"); row.textContent = text; return row; }));
  checklist.hidden = warnings.length === 0;
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

function nutritionProductSourceText(product) {
  const sourceLabel = product.source === "packaging_label" ? "Verpackungsangabe" : (product.source || "Lokales Produkt");
  const barcodeLabel = product.barcode ? ` · EAN ${product.barcode}` : "";
  return sourceLabel + barcodeLabel;
}

function appendNutritionProductActions(card, product, local) {
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
}

function renderNutritionProducts(products, { local = true, targetId = "#nutritionProducts" } = {}) {
  const target = document.querySelector(targetId);
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
    const source = document.createElement("small"); source.textContent = nutritionProductSourceText(product);
    const basis = document.createElement("small"); basis.textContent = product.basis_amount ? `Basis: ${product.basis_amount} ${product.basis_unit || "g"}` : "Bezugsmenge unbekannt";
    card.append(title, detail, source, basis);
    appendNutritionProductActions(card, product, local);
    target.append(card);
  }
}

async function loadNutritionDatabase(query = "") {
  const generation = state.sessionGeneration;
  const target = document.querySelector("#nutritionDatabase");
  if (!target) return;
  try {
    const params = query ? `&q=${encodeURIComponent(query)}` : "";
    const result = await api(`/api/nutrition/products?source=database${params}`);
    if (generation !== state.sessionGeneration) return;
    const foods = result.foods || [];
    if (!foods.length) { target.textContent = "Noch keine Produkte aus der Datenbank gespeichert."; return; }
    renderNutritionProducts(foods, { local: false, targetId: "#nutritionDatabase" });
    target.querySelectorAll(".nutrition-product-card").forEach((card, index) => {
      const food = foods[index];
      if (food.stored_at) card.querySelector("small").append(` · Stand vom ${new Date(food.stored_at).toLocaleDateString("de-DE")}`);
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "secondary-button"; remove.textContent = "Aus Datenbank entfernen";
      remove.addEventListener("click", async () => {
        if (!await requestConfirmation(`Eintrag „${food.name}“ aus der Datenbank entfernen? Eigene Produkte bleiben erhalten.`)) return;
        try { await api("/api/nutrition/products/database/delete", { method: "POST", body: JSON.stringify({ id: food.id, confirmed: true }) }); await loadNutritionDatabase(query); }
        catch (error) { document.querySelector("#nutritionProductStatus").textContent = `Eintrag konnte nicht entfernt werden: ${error.message}`; }
      });
      card.append(remove);
    });
  } catch (error) { if (generation === state.sessionGeneration) target.textContent = `Datenbank konnte nicht geladen werden: ${error.message}`; }
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
  jumpToLatestMessages();
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
    const params = query ? `?q=${encodeURIComponent(query)}` : "";
    const result = await api(`/api/nutrition/products${params}`);
    if (!isCurrentNutritionProductLoad(sequence, generation, expectedQuery)) return;
    void loadNutritionDatabase(query);
    renderNutritionProducts(result.products || []);
    if (!preserveLookup) status.textContent = result.products?.length ? "" : "Keine lokalen Produkte gefunden.";
  } catch (error) {
    showNutritionProductLoadError(preserveLookup, sequence, generation, expectedQuery, error);
    if (throwOnError) throw error;
  }
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
    ++nutritionProductLoadSequence;
    nutritionLookupResultShown = true;
    const product = result.product || result.foods?.[0] || result.products?.[0] || null;
    const isLocal = result.local !== false && result.source !== "open_food_facts";
    const lookup = document.querySelector("#nutritionLookupResult");
    if (lookup) lookup.hidden = false;
    renderNutritionProducts(product ? [{ ...product, local: isLocal }] : [], { local: isLocal, targetId: "#nutritionLookupResult" });
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
