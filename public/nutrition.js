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

async function nutritionCoachRequest(text) {
  const input = document.querySelector("#messageInput");
  if (!input.value.trim()) {
    input.value = text;
    input.dispatchEvent(new Event("input"));
  }
  if (await applyNavigationRoute("coach", { historyMode: "push" })) input.focus();
}

function nutritionButton(label, text) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.textContent = label;
  button.addEventListener("click", () => void nutritionCoachRequest(text));
  return button;
}

function nutritionCard(item, template, date) {
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
  const sourceLabels = { coach: "Coach-Schätzung", photo: "Foto-Schätzung", voice: "Spracheingabe", manual: "Manuelle Angabe" };
  const sourceLabel = sourceLabels[item.source] || "Erfasst";
  const syncLabel = item.sync_state === "synced" ? " · Synchronisiert" : " · Lokal";
  source.textContent = sourceLabel + (template ? "" : syncLabel);
  const actions = document.createElement("div");
  const safeMealName = JSON.stringify(item.name);
  actions.className = "nutrition-actions";
  if (template) {
    const logPrompt = `Ich habe am ${date} die gespeicherte Mahlzeit ${safeMealName} (Vorlagen-ID ${item.id}) gegessen. Bitte kläre die Portionsanzahl mit mir.`;
    actions.append(nutritionButton("Beim Coach erfassen", logPrompt));
  }
  const changePrompt = template
    ? `Ich möchte die gespeicherte Mahlzeit ${safeMealName} (Vorlagen-ID ${item.id}) dauerhaft ändern. Bitte frage mich nach den Änderungen und zeige die neue Vorlage zur Bestätigung.`
    : `Ich möchte den Ernährungseintrag vom ${date} (Eintrags-ID ${item.id}) korrigieren. Bitte frage mich nach der Änderung.`;
  actions.append(nutritionButton("Ändern beim Coach", changePrompt));
  const deleteTarget = template ? "die Mahlzeitvorlage" : "den Ernährungseintrag";
  const deletePrompt = `Ich möchte ${deleteTarget} mit ID ${item.id} löschen. Bitte bestätige vorher mit mir, dass du den richtigen Eintrag gefunden hast.`;
  actions.append(nutritionButton("Löschen beim Coach", deletePrompt));
  card.append(title, description, values, source, actions);
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
    const [day, saved] = await Promise.all([
      api(`/api/nutrition/day${dateInput.value ? `?date=${encodeURIComponent(dateInput.value)}` : ""}`),
      api("/api/nutrition/templates"),
    ]);
    if (sequence !== nutritionLoadSequence || generation !== state.sessionGeneration) return;
    dateInput.value = day.date;
    status.textContent = day.entry_count ? "Summen der erfassten Mahlzeiten · Schätzungen sind Näherungswerte" : "Noch keine Mahlzeiten erfasst. Das bedeutet nicht, dass du nichts gegessen hast.";
    const totals = document.querySelector("#nutritionTotals");
    for (const [label, key, unit] of [["Kalorien", "kcal", "kcal"], ["Kohlenhydrate", "carbs_g", "g"], ["Protein", "protein_g", "g"], ["Fett", "fat_g", "g"]]) {
      const tile = document.createElement("div");
      tile.className = "nutrition-total";
      const value = document.createElement("strong");
      const known = day.entries.some((entry) => entry[key] != null);
      value.textContent = `${known ? day[`total_${key}`] : "–"} ${unit}`;
      const caption = document.createElement("span");
      caption.textContent = label + (known && day.entries.some((entry) => entry[key] == null) ? " · unvollständig" : "");
      tile.append(value, caption);
      totals.append(tile);
    }
    document.querySelector("#nutritionEntries").replaceChildren(...day.entries.map((item) => nutritionCard(item, false, day.date)));
    const templates = document.querySelector("#nutritionTemplates");
    templates.replaceChildren(...saved.templates.map((item) => nutritionCard(item, true, day.date)));
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
document.querySelector("#nutritionLog").addEventListener("click", () => void nutritionCoachRequest(`Ich möchte mein Essen für ${document.querySelector("#nutritionDate").value || "heute"} erfassen: `));
document.querySelector("#nutritionDefine").addEventListener("click", () => void nutritionCoachRequest("Ich möchte eine wiederverwendbare Mahlzeit definieren. Bitte kläre Zutaten und Mengen für eine Portion mit mir und zeige Kalorien und Makros zur Bestätigung. Noch keinen Verzehr erfassen."));

function resetNutritionView() {
  ++nutritionLoadSequence;
  document.querySelector("#nutritionDate").value = "";
  for (const id of ["nutritionEntries", "nutritionTemplates", "nutritionTotals", "nutritionStatus"]) document.getElementById(id).replaceChildren();
}
