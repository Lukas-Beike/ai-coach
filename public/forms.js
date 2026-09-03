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
