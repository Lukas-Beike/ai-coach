function contextField(labelText, field, value = "", options = {}) {
  const label = document.createElement("label");
  label.textContent = labelText;
  let input;
  if (options.choices) {
    input = document.createElement("select");
    for (const choice of options.choices) {
      const option = document.createElement("option");
      option.value = typeof choice === "string" ? choice : choice.value;
      option.textContent = typeof choice === "string" ? choice : choice.label;
      input.append(option);
    }
  } else if (options.multiline) {
    input = document.createElement("textarea");
    input.rows = options.rows || 2;
  } else {
    input = document.createElement("input");
    input.type = options.type || "text";
  }
  input.dataset.field = field;
  input.value = value || "";
  if (options.placeholder) input.placeholder = options.placeholder;
  label.append(input);
  return label;
}

function collectCompetitions() {
  return [...document.querySelectorAll(".competition-editor")].map((card) => {
    const competition = { id: card.dataset.id || "" };
    card.querySelectorAll("[data-field]").forEach((input) => {
      const field = input.dataset.field;
      const value = input.value.trim();
      if (field === "moving_time") {
        const [hours, minutes] = value.split(":").map(Number);
        competition[field] = value && Number.isFinite(hours) && Number.isFinite(minutes) ? hours * 3600 + minutes * 60 : "";
      } else if (field === "distance") {
        const kilometers = Number(value.replace(",", "."));
        competition[field] = value && Number.isFinite(kilometers) ? String(Math.round(kilometers * 1000)) : "";
      } else competition[field] = value;
    });
    return competition;
  });
}
