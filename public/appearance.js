(() => {
  let choice = "system";
  try { choice = localStorage.getItem("intervals-coach-appearance") || "system"; } catch { }
  if (!["system", "light", "dark"].includes(choice)) choice = "system";
  const light = choice === "light" || (choice === "system" && globalThis.matchMedia?.("(prefers-color-scheme: light)").matches);
  document.documentElement.dataset.theme = light ? "light" : "dark";
  const themeColor = document.querySelector("meta[name='theme-color']");
  if (themeColor) themeColor.content = light ? "#ffffff" : "#0b0b0d";
})();
