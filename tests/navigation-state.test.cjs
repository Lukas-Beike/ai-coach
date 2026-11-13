const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const { babelParse, traverse, loadPublicScript, extractFunctions } = require("./frontend-harness.cjs");

const plain = (value) => JSON.parse(JSON.stringify(value));

// A panel or nav item that records what the router does to it.
function element(dataset = {}) {
  const classes = new Set();
  const attributes = {};
  const focused = [];
  return {
    dataset, classes, attributes, focused,
    classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name) },
    setAttribute: (name, value) => { attributes[name] = value; },
    removeAttribute: (name) => { delete attributes[name]; },
    focus: (options) => focused.push(options),
  };
}

// State and navigation run in one context, with a small page of five nav items and their panels.
function router({ hash = "" } = {}) {
  const panels = new Map(["chatPanel", "workoutsPanel", "nutritionPanel", "dataPanel", "settingsPanel", "profilePanel"].map((id) => [id, element()]));
  const items = new Map([["coach", "chatPanel"], ["plan", "workoutsPanel"], ["nutrition", "nutritionPanel"], ["analysis", "dataPanel"], ["more", "settingsPanel"]]
    .map(([route, panel]) => [route, element({ route, panel })]));
  const listeners = [];
  const history = [];
  const location = { hash };
  const document = {
    querySelectorAll(selector) {
      if (selector === ".nav-item, .panel") return [...items.values(), ...panels.values()];
      if (selector === ".nav-item") return [...items.values()];
      const route = /data-route="([^"]+)"/.exec(selector)?.[1];
      return items.has(route) ? [items.get(route)] : [];
    },
    querySelector(selector) {
      const route = /data-route="([^"]+)"/.exec(selector)?.[1];
      if (route) return items.get(route) || null;
      if (selector === "#appShell") return { hidden: false };
      if (selector === ".nav-item.active") return [...items.values()].find((item) => item.classes.has("active")) || null;
      return panels.get(selector.slice(1)) || null;
    },
  };
  const context = loadPublicScript(["state.js", "navigation.js"], {
    crypto: { randomUUID: () => "00000000-0000-4000-8000-000000000000" },
    document, location,
    history: { pushState: (...args) => { history.push(["push", ...args]); location.hash = args[2]; }, replaceState: (...args) => { history.push(["replace", ...args]); location.hash = args[2]; } },
    addEventListener: (type, handler) => listeners.push([type, handler]),
    scrollY: 0,
  });
  const calls = [];
  const handlers = {
    unsaved: false, confirm: true,
    hasUnsavedChanges: () => handlers.unsaved,
    confirmDiscardChanges: async () => handlers.confirm,
    discardUnsavedChanges: () => calls.push("discard"),
    renderActiveRoute: (...args) => calls.push(["render", ...args]),
    renderStatus: () => {},
    restoreRouteScroll: () => {},
    ensureRouteData: (route) => calls.push(["data", route]),
  };
  return { context, panels, items, listeners, history, location, handlers, calls };
}

test("the app state starts with its defaults and refuses to mint tokens without a secure generator", () => {
  const { context } = router();
  const state = context.AppState.state;
  assert.ok(Object.isFrozen(context.AppState));
  assert.equal(state.chatScrollRestoring, false);
  assert.equal(state.planSegment, "overview");
  assert.equal(state.route, null);
  assert.equal(context.AppState.secureToken("tab"), "tab-00000000-0000-4000-8000-000000000000");
  assert.throws(() => loadPublicScript("state.js", {}).AppState.secureToken("tab"), /Secure random generator unavailable/);
});

test("the route and plan segment are set through the state owner", () => {
  const { context } = router();
  assert.equal(context.AppState.setRoute("plan/library"), "plan/library");
  assert.equal(context.AppState.setPlanSegment("season"), "season");
  assert.deepEqual([context.AppState.state.route, context.AppState.state.planSegment], ["plan/library", "season"]);
});

test("the routes name their panels and the segments the views offer", () => {
  const { context } = router();
  const { routes, planSegments, moreSegments, linkRoutes, defaultRoute } = context.AppNavigation;
  assert.ok(Object.isFrozen(context.AppNavigation));
  assert.deepEqual(plain(planSegments), ["overview", "library", "season"]);
  assert.deepEqual(plain(moreSegments), ["profile", "equipment", "connections", "coach", "operations", "appearance"]);
  assert.deepEqual(plain(Object.keys(linkRoutes)), ["coach", "plan", "nutrition", "analysis", "more"]);
  assert.equal(defaultRoute, "coach");
  assert.equal(routes.plan, "workoutsPanel");
  assert.equal(routes["plan/overview"], "workoutsPanel");
  assert.equal(routes["plan/library"], "workoutsPanel");
  assert.equal(routes.analysis, "dataPanel");
  assert.equal(routes["analysis/running"], "dataPanel");
  assert.equal(routes["analysis/cycling"], "dataPanel");
  assert.equal(routes["more/profile"], "profilePanel");
});

test("a hash names a known route in any case, and a removed route falls back to the Coach", () => {
  const { context } = router();
  const { routeFromHash, hashContainsKnownRoute } = context.AppRouter;
  assert.equal(routeFromHash("#Plan/Overview"), "plan/overview");
  assert.equal(routeFromHash("#analysis/running"), "analysis/running");
  // The former Leistung link opens Laufen (#2265).
  assert.equal(routeFromHash("#analysis/performance"), "analysis/running");
  for (const removed of ["#today", "#activities", "#planned", "#performance", "#analysis/history", "", "#unknown"]) {
    assert.equal(routeFromHash(removed), "coach", removed);
    assert.equal(hashContainsKnownRoute(removed), false, removed);
  }
  assert.equal(hashContainsKnownRoute("#more"), true);
});

test("the route parts fall back to the first plan segment and the connections section", () => {
  const { context } = router();
  const { planSegmentFromRoute, moreSegmentFromRoute, baseRoute } = context.AppRouter;
  assert.equal(planSegmentFromRoute("plan/library"), "library");
  assert.equal(planSegmentFromRoute("plan/other"), "overview");
  assert.equal(moreSegmentFromRoute("more/operations"), "operations");
  assert.equal(moreSegmentFromRoute("more"), "connections");
  assert.equal(baseRoute("analysis/running"), "analysis");
  assert.equal(baseRoute(null), "coach");
});

test("the router needs every handler before it navigates and listens to the hash once", async () => {
  const { context, handlers, listeners } = router();
  await assert.rejects(context.AppRouter.navigate("plan"), /AppRouter is not configured/);
  assert.throws(() => context.AppRouter.configure({ ...handlers, ensureRouteData: undefined }), /requires all navigation handlers/);
  assert.throws(() => context.AppRouter.configure(null), /requires all navigation handlers/);
  assert.equal(listeners.length, 0);
  context.AppRouter.configure(handlers);
  context.AppRouter.configure(handlers);
  assert.deepEqual(listeners.map(([type]) => type), ["hashchange"]);
  assert.equal(listeners[0][1], context.AppRouter.syncFromHash);
});

test("navigating shows the panel and its nav item, records the history and focuses the panel", async () => {
  const { context, handlers, panels, items, history, calls } = router();
  context.AppRouter.configure(handlers);
  assert.equal(await context.AppRouter.navigate("plan/library", { historyMode: "push" }), true);
  assert.equal(context.AppState.state.route, "plan/library");
  assert.equal(panels.get("workoutsPanel").classes.has("active"), true);
  assert.equal(panels.get("chatPanel").classes.has("active"), false);
  assert.equal(items.get("plan").attributes["aria-current"], "page");
  assert.equal(items.get("coach").attributes["aria-current"], undefined);
  assert.deepEqual(plain(history), [["push", { route: "plan/library" }, "", "#plan/library"]]);
  assert.deepEqual(plain(calls), [["render", "plan", "plan/library"], ["data", "plan/library"]]);
  assert.equal(panels.get("workoutsPanel").attributes.tabindex, "-1");
  assert.deepEqual(plain(panels.get("workoutsPanel").focused), [{ preventScroll: true }]);
});

test("an unknown route opens the Coach, and a hash change applies the hash route", async () => {
  const { context, handlers, panels, location } = router();
  context.AppRouter.configure(handlers);
  await context.AppRouter.navigate("nowhere");
  assert.equal(context.AppState.state.route, "coach");
  assert.equal(panels.get("chatPanel").classes.has("active"), true);
  location.hash = "#analysis/cycling";
  await context.AppRouter.syncFromHash();
  assert.equal(context.AppState.state.route, "analysis/cycling");
  assert.equal(panels.get("dataPanel").classes.has("active"), true);
});

test("leaving a panel with unsaved changes asks first and stays when the athlete declines", async () => {
  const { context, handlers, calls } = router();
  context.AppRouter.configure(handlers);
  await context.AppRouter.navigate("coach");
  handlers.unsaved = true;
  handlers.confirm = false;
  calls.length = 0;
  assert.equal(await context.AppRouter.navigate("plan"), false);
  assert.equal(context.AppState.state.route, "coach");
  assert.deepEqual(plain(calls), []);
  handlers.confirm = true;
  assert.equal(await context.AppRouter.navigate("plan"), true);
  assert.equal(context.AppState.state.route, "plan");
  assert.equal(calls[0], "discard");
});

// docs/view-catalogue.md is generated from the router's own tables (the routes with their view descriptors) and
// from the state and confirmation texts found in public/*.js. Regenerate it with:
// node tests/navigation-state.test.cjs --write
const CATALOGUE = path.join(__dirname, "..", "docs", "view-catalogue.md");
const PUBLIC = path.join(__dirname, "..", "public");
const STATE_NAMES = ["loading", "empty", "error", "notConfigured", "offline"];
const publicFiles = () => fs.readdirSync(PUBLIC).filter((file) => file.endsWith(".js")).sort();
const publicSource = (file) => fs.readFileSync(path.join(PUBLIC, file), "utf8").replaceAll("\r\n", "\n");

// Problems of the view descriptors: a route without one, a descriptor without a route, an unknown state, and a
// read path or control label that none of the public sources contains.
function contractProblems(routes, views, scripts, markup) {
  const problems = [];
  for (const route of Object.keys(routes)) if (!Object.hasOwn(views, route)) problems.push(`${route} has no view descriptor`);
  for (const [route, view] of Object.entries(views)) {
    if (!Object.hasOwn(routes, route)) problems.push(`${route} is no route`);
    for (const state of view.states) if (!STATE_NAMES.includes(state)) problems.push(`${route}: unknown state ${state}`);
    for (const load of view.loads) if (!scripts.includes(load)) problems.push(`${route}: no code reads ${load}`);
    for (const action of view.actions) if (!scripts.includes(action) && !markup.includes(action)) problems.push(`${route}: no control labelled ${action}`);
    if (!view.actions.length || !view.states.length) problems.push(`${route}: empty actions or states`);
  }
  return problems;
}

test("every route has one view descriptor that the sources bear out", () => {
  const { routes, views } = loadPublicScript("navigation.js").AppNavigation;
  const scripts = publicFiles().map(publicSource).join("\n");
  const markup = publicSource("index.html").replaceAll("&amp;", "&");
  assert.deepEqual(contractProblems(routes, views, scripts, markup), []);
  assert.ok(Object.isFrozen(views) && Object.isFrozen(views.coach) && Object.isFrozen(views.coach.loads));
});

test("a missing, extra or unfounded view descriptor is a problem", () => {
  const view = { loads: ["/api/a"], actions: ["Los"], states: ["empty"] };
  assert.deepEqual(contractProblems({ a: "p", b: "p" }, { a: view, c: view }, "/api/a", "Los"), ["b has no view descriptor", "c is no route"]);
  const broken = { loads: ["/api/x"], actions: ["Weg"], states: ["busy"] };
  assert.deepEqual(contractProblems({ a: "p" }, { a: broken }, "/api/a", "Los"),
    ["a: unknown state busy", "a: no code reads /api/x", "a: no control labelled Weg"]);
});

// The state helpers of components.js and the argument positions that carry text.
const STATE_HELPERS = { createEmptyState: [0, 1], createLoadingState: [0], createErrorState: [0], markValueMissing: [1] };
// CSS classes that public/ uses only for empty-state paragraphs.
const EMPTY_CLASSES = ["empty", "context-empty"];

function functionName(callPath) {
  const key = (name) => name?.name ?? name?.value;
  for (let up = callPath.parentPath; up; up = up.parentPath) {
    if (!up.isFunction()) continue;
    const { node, parent } = up;
    const name = node.id?.name ?? key(node.key) ?? (parent.type === "VariableDeclarator" ? parent.id.name : null) ?? (parent.type === "ObjectProperty" ? key(parent.key) : null);
    if (name) return name;
  }
  return "(top level)";
}

const fence = (code) => { const ticks = "`".repeat(Math.max(0, ...(code.match(/`+/g) || []).map((run) => run.length)) + 1); return `${ticks} ${code} ${ticks}`; };
const cell = (text) => String(text).replaceAll("|", "\\|").replaceAll("\n", " ");

// A literal argument is its text; anything else is listed as computed with its expression.
function argumentText(node, source) {
  if (!node || node.type === "NullLiteral") return "–";
  if (node.type === "StringLiteral") return cell(node.value);
  if (node.type === "TemplateLiteral" && !node.expressions.length) return cell(node.quasis[0].value.cooked);
  return cell(`(computed) ${fence(source.slice(node.start, node.end).replace(/\s+/g, " "))}`);
}

// Every state helper call and every requestConfirmation call (the app's one confirmation dialog) of public/*.js,
// in file and source order, with the function it sits in.
function scanPublicTexts() {
  const states = [];
  const confirmations = [];
  const defaults = {};
  for (const file of publicFiles()) {
    const source = publicSource(file);
    traverse(babelParse(source, file, false), {
      FunctionDeclaration(item) {
        const { id, params } = item.node;
        if (id.name === "markValueMissing") defaults.text = argumentText(params[1].right, source);
        if (id.name === "requestConfirmation") for (const property of params[1].left.properties) defaults[property.key.name] = argumentText(property.value.right, source);
      },
      CallExpression(item) {
        const { callee, arguments: args } = item.node;
        if (callee.type !== "Identifier") return;
        const where = { file, fn: functionName(item) };
        if (callee.name in STATE_HELPERS) states.push({ ...where, helper: callee.name, texts: STATE_HELPERS[callee.name].map((index) => (args[index] ? argumentText(args[index], source) : null)) });
        // An empty-state paragraph drawn inline with one of the empty-state classes.
        const className = args[1]?.type === "StringLiteral" ? args[1].value : "";
        if (callee.name === "h" && EMPTY_CLASSES.includes(className)) states.push({ ...where, helper: `h(.${className})`, texts: args.slice(2).map((node) => argumentText(node, source)) });
        if (callee.name !== "requestConfirmation") return;
        const options = Object.fromEntries((args[1]?.properties || []).map((property) => [property.key.name, argumentText(property.value, source)]));
        confirmations.push({ ...where, message: argumentText(args[0], source), options });
      },
    });
  }
  // The text a state helper shows when its call gives none is the default of its parameter.
  for (const row of states) row.texts = row.texts.map((text) => text ?? defaults.text);
  return { states, confirmations, defaults };
}

const BEGIN = (name) => `<!-- BEGIN GENERATED ${name} -->\n`;
const END = (name) => `<!-- END GENERATED ${name} -->\n`;

function viewCatalogue() {
  const { routes, views, linkRoutes, defaultRoute, planSegments, moreSegments } = loadPublicScript("navigation.js").AppNavigation;
  const { ROUTE_ALIASES } = extractFunctions("navigation.js", ["ROUTE_ALIASES"]);
  const list = (items, code) => items.map((item) => (code ? `\`${item}\`` : item)).join(", ");
  const lines = [
    `Default route: \`#${defaultRoute}\`. Navigation items: ${Object.values(linkRoutes).map((route) => `\`#${route}\``).join(", ")}.`,
    "",
    "| Route | Panel | Navigation item | Loads | Actions | States |",
    "| --- | --- | --- | --- | --- | --- |",
    ...Object.keys(routes).sort().map((route) => `| \`#${route}\` | \`${routes[route]}\` | \`${linkRoutes[route.split("/")[0]] || route.split("/")[0]}\` | ${list(views[route].loads, true)} | ${list(views[route].actions)} | ${list(views[route].states)} |`),
    "",
    `Kalender segments: ${planSegments.map((segment) => `\`${segment}\``).join(", ")}.`,
    `Mehr segments: ${moreSegments.map((segment) => `\`${segment}\``).join(", ")}.`,
    "",
    "Former routes that open another view:",
    "",
    ...Object.entries(ROUTE_ALIASES).sort().map(([from, to]) => `- \`#${from}\` opens \`#${to}\``),
  ];
  return lines.join("\n") + "\n";
}

function stateTables() {
  const lines = [];
  let file = "";
  for (const row of scanPublicTexts().states) {
    if (row.file !== file) {
      file = row.file;
      lines.push(...(lines.length ? [""] : []), `### \`public/${file}\``, "", "| Function | Helper | Text | Detail |", "| --- | --- | --- | --- |");
    }
    lines.push(`| \`${row.fn}\` | \`${row.helper}\` | ${row.texts[0]} | ${row.texts[1] ?? ""} |`);
  }
  return lines.join("\n") + "\n";
}

function copyDeck() {
  const { confirmations, defaults } = scanPublicTexts();
  const lines = ["| Where | Title | Message | Button |", "| --- | --- | --- | --- |"];
  for (const row of confirmations) {
    lines.push(`| \`public/${row.file}\` \`${row.fn}\` | ${row.options.title ?? defaults.title} | ${row.message} | ${row.options.confirmLabel ?? defaults.confirmLabel} |`);
  }
  return lines.join("\n") + "\n";
}

const ARTEFACTS = { VIEWS: viewCatalogue, STATES: stateTables, COPY: copyDeck };
const catalogueDocument = () => fs.readFileSync(CATALOGUE, "utf8").replaceAll("\r\n", "\n");
const generatedSection = (document, name) => document.split(BEGIN(name))[1].split(END(name))[0];

for (const [name, render] of Object.entries(ARTEFACTS)) {
  test(`the ${name.toLowerCase()} section of the view catalogue is current`, () => {
    assert.equal(generatedSection(catalogueDocument(), name), render(), "Regenerate with: node tests/navigation-state.test.cjs --write");
  });
}

test("the scan finds the state helper calls with their text and the confirmation dialogs with the dialog defaults", () => {
  const { states, confirmations, defaults } = scanPublicTexts();
  assert.deepEqual(states.find((row) => row.fn === "loadPanel" && row.helper === "createLoadingState"), { file: "activity-analysis.js", fn: "loadPanel", helper: "createLoadingState", texts: ["Details werden geladen …"] });
  assert.deepEqual(plain(states.find((row) => row.helper === "createEmptyState" && row.fn === "analysisEmptyCard").texts), ["(computed) ` ANALYSIS_EMPTY_TITLES[segment] `", "(computed) ` cause `"]);
  assert.deepEqual([defaults.title, defaults.confirmLabel, defaults.text], ["Aktion bestätigen", "Bestätigen", "nicht erfasst"]);
  assert.deepEqual(plain(states.find((row) => row.fn === "kcalValue").texts), ["nicht erfasst"]);
  const discard = confirmations.find((row) => row.fn === "confirmDiscardDraft");
  assert.deepEqual([discard.message, discard.options.title], ["Ungespeicherte Änderungen verwerfen?", "Änderungen verwerfen?"]);
  assert.ok(confirmations.some((row) => row.message.startsWith("(computed)")));
});

if (process.argv.includes("--write")) {
  let document = catalogueDocument();
  for (const [name, render] of Object.entries(ARTEFACTS)) {
    const [before, rest] = document.split(BEGIN(name));
    document = before + BEGIN(name) + render() + END(name) + rest.split(END(name))[1];
  }
  fs.writeFileSync(CATALOGUE, document);
}
