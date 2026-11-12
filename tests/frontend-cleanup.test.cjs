const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { loadPublicScript } = require("./frontend-harness.cjs");

const publicDir = path.join(__dirname, "../public");
const read = (name) => fs.readFileSync(path.join(publicDir, name), "utf8").replace(/\r\n/g, "\n");
const index = read("index.html");
const worker = read("service-worker.js");
const scripts = fs.readdirSync(publicDir).filter((name) => name.endsWith(".js"));

function workerAssets() {
  const match = /const ASSETS = (\[.*?\]);/s.exec(worker);
  assert.ok(match, "service-worker.js must declare ASSETS");
  return JSON.parse(match[1]);
}

test("every service-worker asset exists in public/ and is referenced from index.html or the stylesheet", () => {
  const assets = workerAssets().filter((asset) => asset !== "/");
  const styles = read("styles.css");
  assert.ok(assets.length > 0);
  // Icons only the manifest names are cached for the offline install.
  const manifestIcons = new Set(JSON.parse(read("manifest.webmanifest")).icons.map((icon) => icon.src).filter((src) => !index.includes(`"${src}`)));
  for (const asset of assets) {
    const file = asset.split("?")[0].slice(1);
    assert.ok(fs.existsSync(path.join(publicDir, file)), `${asset} is cached but missing from public/`);
    if (manifestIcons.has(asset)) continue;
    if (file === "manifest.webmanifest") assert.ok(index.includes(`href="/${file}"`), `${file} is not linked from index.html`);
    else assert.ok(index.includes(`"${asset}"`) || styles.includes(`url("${asset}")`), `${asset} is not referenced from index.html or styles.css`);
  }
});

test("every script and stylesheet of index.html is cached by the service worker", () => {
  const assets = new Set(workerAssets());
  // Sources carry no versions; the server stamps them when serving (#1902).
  const referenced = [...index.matchAll(/(?:src|href)="(\/[^"?#]+\.(?:js|css|svg|png))"/g)].map((match) => match[1]);
  assert.ok(referenced.length > 0);
  for (const asset of referenced) assert.ok(assets.has(asset), `${asset} is referenced but not cached`);
});

test("removed frontend symbols and files are gone from public/", () => {
  assert.ok(!fs.existsSync(path.join(publicDir, "forms.js")));
  const sources = [...scripts, "index.html", "service-worker.js"].map(read).join("\n");
  for (const removed of ["renderTrainingPlans", "trainingPlanCard", "trainingPlanEntry", "appendLocalEquipment", "providerShortLabel", "performanceSection", "calendarHorizonText", "calendarHorizonHint", "planningSummary", "forms.js", "contextField", "jumpToChatComposer", "chat-composer-hidden", "coachQueuedMessages", ">Neue Nachricht<", "/api/activities?limit=250", "chatResetButton", "aiProviderSelect"]) {
    assert.ok(!sources.includes(removed), `${removed} is still referenced`);
  }
  assert.ok(!/id="trainingPlans"/.test(index));
});

test("removed CSS classes and tokens are no longer defined", () => {
  const styles = read("styles.css");
  for (const cls of ["weekly-chart", "weekly-load-line", "weekly-load-point", "weekly-sport-legend", "coach-overview", "garmin-panel", "replan-preview", "replan-change", "adaptive-planning-dialog", "planned-day-form", "planned-day-metrics", "estimate-note", "training-plan", "eyebrow", "chat-composer-hidden"]) {
    assert.ok(!new RegExp(String.raw`\.${cls}(?![\w-])`).test(styles), `.${cls} is still defined`);
  }
  for (const token of ["bg-elevated", "planned-entry-shadow", "selected-surface", "session-soft", "space-1", "space-2", "space-6", "estimate-ink", "bottom-nav-clearance", "chat-fixed-ui-clearance"]) {
    assert.ok(!new RegExp(String.raw`--${token}(?![\w-])`).test(styles), `--${token} is still defined`);
  }
  assert.ok(!styles.includes(".quick-message-templates::after"), "the quick-start fade overlay is back");
});

test("collapsible summary titles are never hidden by a merged selector list", () => {
  const styles = read("styles.css");
  for (const match of styles.matchAll(/([^{}]*collapsible-summary-title[^{}]*)\{([^}]*)\}/g)) {
    assert.ok(!/display:\s*none/.test(match[2]), `${match[1].trim()} is hidden`);
  }
});

test("no font size below the legibility floor of .72rem is declared", () => {
  // The only exception: five bottom-nav labels at 320 px width.
  const narrowNav = /@media \(max-width: 340px\) \{\s*\.nav-item \{ font-size: \.66rem; letter-spacing: -\.01em; \}\s*\}/;
  const all = read("styles.css");
  assert.match(all, narrowNav);
  const styles = all.replace(narrowNav, "");
  for (const match of styles.matchAll(/font(?:-size)?:\s*(\.?\d*\.?\d+)rem/g)) {
    assert.ok(Number(match[1]) >= 0.72, `font size ${match[1]}rem is below .72rem`);
  }
});

test("UI strings use one German vocabulary", () => {
  const sources = [...scripts.filter((name) => name !== "service-worker.js").map((name) => [name, read(name)]), ["index.html", index]];
  const forbidden = ["Load geplant", "Sync-Status unter Mehr", "Kennwort", "LTHR (bpm)", "Schwellen-HF", "Schwellen-Herzfrequenz", "Retry-Verlauf", "Kein automatischer Retry", "Synchronisation"];
  for (const [name, source] of sources) {
    for (const text of forbidden) assert.ok(!source.includes(text), `${name} contains "${text}"`);
  }
  assert.ok(!/"Load\b|`Load\b/.test(read("plan-views.js")), "plan-views.js labels the load as Load");
});

test("the manifest matches the app colours and the downloads use the Pacecraft name", () => {
  const manifest = JSON.parse(read("manifest.webmanifest"));
  const themeColor = /<meta name="theme-color" content="(#[0-9a-f]{6})"/i.exec(index)[1];
  assert.equal(manifest.theme_color, themeColor);
  assert.equal(manifest.background_color, themeColor);
  const settings = read("settings.js");
  assert.ok(settings.includes("`pacecraft-database-${todayIso()}.backup`"));
  assert.ok(settings.includes("`pacecraft-export-${todayIso()}.zip`"));
  assert.ok(!settings.includes("intervals-coach-database") && !settings.includes("intervals-coach-export"));
});

test("only the kept explanations remain as helper texts", () => {
  for (const text of ["nicht das Passwort", "Bestätigungscode geschickt", "CC BY 4.0", "nur mit demselben APP_PASSWORD wiederhergestellt", "in Coach-Anfragen an OpenAI eingehen"]) {
    assert.ok(index.includes(text), `${text} must stay`);
  }
  for (const text of ["Leer = Standard-Obergrenzen", "Optional, aus Labortest", "-1 lädt alle", "0 = keine vergangene Woche", "Wähle die Balance", "Thinking Level steuert"]) {
    assert.ok(!index.includes(text), `${text} was removed`);
  }
  assert.ok(!/class="eyebrow"/.test(index));
});

test("a Coach link names its host when the label does not, and escapes it", () => {
  const context = loadPublicScript("views.js", { URL });
  const differing = context.inlineMarkdown("[Mehr dazu](https://www.example.invalid/path?a=1&b=2)");
  assert.ok(differing.includes('<a href="https://www.example.invalid/path?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">Mehr dazu</a><span class="link-host"> (example.invalid)</span>'));
  assert.ok(!context.inlineMarkdown("[example.invalid/path](https://example.invalid/path)").includes("link-host"));
  assert.ok(context.inlineMarkdown("[Quelle](https://example.invalid/x)").includes("(example.invalid)</span>"));
});
