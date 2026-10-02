// Read-only nutrition views; every write remains an explicit Coach request.
let nutritionLoadSequence = 0;

function renderNutritionSegments(route) {
  const meals = route === "nutrition/meals";
  document.querySelector("#nutritionDiary").hidden = meals;
  document.querySelector("#nutritionMeals").hidden = !meals;
  document.querySelectorAll("[data-nutrition-segment]").forEach((link) => {
    const active = link.dataset.nutritionSegment === (meals ? "meals" : "diary");
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
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
  values.textContent = `${item.kcal} kcal · KH ${item.carbs_g ?? "–"} g · Protein ${item.protein_g ?? "–"} g · Fett ${item.fat_g ?? "–"} g${template ? " / Portion" : ""}`;
  const source = document.createElement("small");
  const sourceLabels = { coach: "Coach-Schätzung", photo: "Foto-Schätzung", voice: "Sprach-Schätzung", manual: "Manuelle Angabe" };
  const sourceLabel = sourceLabels[item.source] || "Erfasst";
  const syncLabel = item.sync_state === "synced" ? " · Synchronisiert" : " · Lokal";
  const basis = item.nutrition_basis;
  let basisLabel = sourceLabel;
  if (basis?.kind === "database") basisLabel = "Datenbankberechnung · " + basis.ingredients.map((food) => `${food.source}: ${food.name}, ${food.amount} ${food.unit} (Basis 100 ${food.basis_unit})`).join("; ");
  else if (basis?.kind === "manual_correction") basisLabel = "Manuell korrigierte Nährwerte";
  else if (basis?.kind === "packaging_label") basisLabel = "Verpackungsangabe";
  source.textContent = basisLabel + (template ? "" : syncLabel);
  card.append(title, description, values, source);
  return card;
}

async function loadNutrition() {
  const sequence = ++nutritionLoadSequence;
  const generation = state.sessionGeneration;
  const dateInput = document.querySelector("#nutritionDate");
  const status = document.querySelector("#nutritionStatus");
  status.textContent = "Ernährung wird geladen…";
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
    status.textContent = day.entry_count ? "" : "Noch keine Mahlzeiten erfasst. Das bedeutet nicht, dass du nichts gegessen hast.";
    const totals = document.querySelector("#nutritionTotals");
    for (const [label, key, unit] of [["Kalorien", "kcal", "kcal"], ["Kohlenhydrate", "carbs_g", "g"], ["Protein", "protein_g", "g"], ["Fett", "fat_g", "g"]]) {
      const tile = document.createElement("div");
      tile.className = "nutrition-total";
      const value = document.createElement("strong");
      const known = day.entries.some((entry) => entry[key] != null);
      const total = day[`total_${key}`];
      value.textContent = `${known ? total : "–"} ${unit}`;
      const caption = document.createElement("span");
      caption.textContent = label + (known && day.entries.some((entry) => entry[key] == null) ? " · unvollständig" : "");
      tile.append(value, caption);
      totals.append(tile);
    }
    document.querySelector("#nutritionEntries").replaceChildren(...day.entries.map((item) => nutritionCard(item, false)));
    const templates = document.querySelector("#nutritionTemplates");
    templates.replaceChildren(...saved.templates.map((item) => nutritionCard(item, true)));
    if (!saved.templates.length) templates.textContent = "Noch keine gespeicherten Mahlzeiten. Definiere dein erstes Standardfrühstück mit dem Coach.";
  } catch (error) {
    if (sequence === nutritionLoadSequence && generation === state.sessionGeneration) status.textContent = `Ernährung konnte nicht geladen werden: ${error.message}`;
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
  document.querySelector("#nutritionDate").value = "";
  for (const id of ["nutritionEntries", "nutritionTemplates", "nutritionTotals", "nutritionStatus"]) document.getElementById(id).replaceChildren();
}
