// Shared harness for the frontend unit tests: run public scripts in a vm context, pull named
// functions out of a script by AST (position in the file does not matter), and a minimal fake DOM.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
// A node_modules installed before package-lock.json changed (a rebase onto a new dependency)
// stops here with the fix, not later with an ENOENT inside a test (#2690). npm records what it
// installed in node_modules/.package-lock.json; an optional package for another platform is absent.
function staleInstall(root = path.join(__dirname, "..")) {
  const packages = (file) => {
    try {
      return JSON.parse(fs.readFileSync(path.join(root, file), "utf8")).packages ?? {};
    } catch {
      return {};
    }
  };
  const [locked, installed] = [packages("package-lock.json"), packages("node_modules/.package-lock.json")];
  return Object.keys(locked)
    .filter((key) => key.startsWith("node_modules/") && installed[key]?.version !== locked[key].version)
    .filter((key) => installed[key] || !locked[key].optional);
}
const stale = staleInstall();
if (stale.length) {
  throw new Error(`node_modules does not match package-lock.json (${stale.slice(0, 3).join(", ")}${stale.length > 3 ? ", ..." : ""}): run npm ci --ignore-scripts`);
}
const { babelParse, traverse } = require("../node_modules/playwright/lib/transform/babelBundle.js"); // NOSONAR: issue #2090 asks for the Babel parser Playwright bundles; no other parser is installed.

function readPublic(file) {
  return fs.readFileSync(path.join(__dirname, "../public", file), "utf8").replaceAll("\r\n", "\n");
}

// `globals` is a plain object of sandbox globals (contextified in place, so a test may keep
// reaching it), or an existing vm context to run into.
function contextFor(globals) {
  return vm.isContext(globals) ? globals : vm.createContext(globals);
}

// Scripts that render get the element helpers of components.js unless the test stubs them.
function provideElementHelpers(files, globals) {
  if ([files].flat().includes("components.js") || !globals.document || "h" in globals) return;
  const { h, table, svgNode } = extractFunctions("components.js", ["h", "SVG_NS", "svgNode", "table"], { document: globals.document });
  Object.assign(globals, { h, table, svgNode });
}

// Runs whole public files (one name or a list, in order) and returns the context. The element
// helpers arrive after the files ran, as components.js loads after them in index.html.
function loadPublicScript(files, globals = {}) {
  const context = contextFor(globals);
  for (const file of [files].flat()) new vm.Script(readPublic(file), { filename: file }).runInContext(context); // NOSONAR: test-only, runs the repository's own public/ files.
  provideElementHelpers(files, context);
  return context;
}

// Runs only the named function declarations or consts of a public file (top level, or directly
// inside a wrapping IIFE) and publishes each name as a property of the returned context.
function extractFunctions(file, names, globals = {}) {
  provideElementHelpers(file, globals);
  const source = readPublic(file);
  const found = new Map();
  const outer = (item) => !item.parentPath.scope.parent?.parent;
  const take = (item, name) => { if (names.includes(name) && outer(item) && !found.has(name)) found.set(name, item.node); };
  traverse(babelParse(source, file, false), {
    FunctionDeclaration: (item) => take(item, item.node.id?.name),
    VariableDeclaration: (item) => item.node.declarations.forEach((declaration) => take(item, declaration.id.name)),
  });
  const missing = names.filter((name) => !found.has(name));
  if (missing.length) throw new Error(`${file} declares no ${missing.join(", ")}`);
  const nodes = [...new Set(found.values())].sort((a, b) => a.start - b.start);
  const code = [...nodes.map((node) => source.slice(node.start, node.end)), ...names.map((name) => `globalThis.${name} = ${name};`)];
  const context = contextFor(globals);
  new vm.Script(code.join("\n"), { filename: file }).runInContext(context); // NOSONAR: test-only, runs code cut from the repository's own public/ files.
  return context;
}

// A minimal element. Beyond the plain fields it records, for the golden tree comparisons, which properties were
// explicitly set (even to "" or false), how often each listener type was registered and the SVG namespace;
// textContent replaces the children and reads all descendant text like in a browser, and querySelector answers ".a", ".a + .b[data-k="v"]"
// and ":scope > .a" (any other selector throws).
class FakeElement {
  constructor(tag = "div") {
    const hidden = { explicit: new Set(), listenerCounts: {}, text: "" };
    for (const [name, value] of Object.entries(hidden)) Object.defineProperty(this, `_${name}`, { value, writable: true });
    Object.assign(this, { tag, tagName: tag.toUpperCase(), children: [], attributes: {}, dataset: {}, style: {}, listeners: {}, className: "", value: "", title: "", disabled: false });
    Object.defineProperty(this.style, "setProperty", { value: (name, value) => { this.style[name] = value; } });
    this.classList = { add: (...names) => { this.className = [this.className, ...names].filter(Boolean).join(" "); } };
    // Properties set after construction count as explicit, whatever their value.
    const set = (target, key, value) => {
      if (!String(key).startsWith("_")) target._explicit.add(key);
      return Reflect.set(target, key, value);
    };
    return new Proxy(this, { set }); // NOSONAR: test fake; only a proxy sees properties explicitly set to "" or false.
  }
  // Like a browser: own text plus all descendant text; exactly the assigned value while it is the only child.
  get textContent() {
    if (this.children.length === 1 && this.children[0] === this._text) return this._text;
    return this.children.map((child) => (child instanceof FakeElement ? child.textContent : String(child))).join("");
  }
  set textContent(value) { this._text = value; this.children = value === "" || value == null ? [] : [value]; }
  get childElementCount() { return this.children.filter((child) => typeof child !== "string").length; }
  get lastElementChild() { return this.children.findLast((child) => typeof child !== "string") ?? null; }
  get isConnected() { return true; }
  remove() { /* Detached nodes are not modelled; the tree stays as built. */ }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this._text = ""; this.children = items; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(type, handler) { this.listeners[type] = handler; this._listenerCounts[type] = (this._listenerCounts[type] || 0) + 1; }
  focus() { this.focused = true; }
  fire(type, event = {}) { return this.listeners[type]({ preventDefault() {}, ...event }); }
  descendants() { return this.children.flatMap((child) => (typeof child === "string" ? [] : [child, ...child.descendants()])); }
  querySelectorAll(selector) {
    const scoped = /^:scope > (.+)$/.exec(selector);
    const pool = scoped ? this.children.filter((child) => typeof child !== "string") : this.descendants();
    return pool.filter((node) => node.matchesSelector(scoped ? scoped[1] : selector, this));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  matchesSelector(selector, root) {
    const parts = /^\.([\w-]+)(?: \+ \.([\w-]+)(?:\[data-([\w-]+)="([^"]*)"\])?)?$/.exec(selector);
    if (!parts) throw new Error(`FakeElement does not support the selector ${selector}`);
    const [, first, second, key, value] = parts;
    const classes = (node) => String(node.className).split(" ");
    if (!second) return classes(this).includes(first);
    const parent = [root, ...root.descendants()].find((node) => node.children.includes(this));
    const before = parent?.children[parent.children.indexOf(this) - 1];
    return classes(this).includes(second) && (!key || this.dataset[key] === value) && Boolean(before) && classes(before).includes(first);
  }
}

// querySelector hands out one element per selector, kept in `nodes`.
function fakeDocument() {
  const nodes = new Map();
  return {
    nodes,
    createElement: (tag) => new FakeElement(tag),
    createElementNS: (namespace, tag) => Object.assign(new FakeElement(tag), { namespace }),
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, new FakeElement());
      return nodes.get(selector);
    },
  };
}

// Text of a fake node and its descendants; the element helper appends text as string children.
const textOf = (node) => {
  if (typeof node !== "object") return String(node);
  return node instanceof FakeElement ? node.children.map(textOf).join("") : `${node.textContent || ""}${node.children.map(textOf).join("")}`;
};

module.exports = { staleInstall, babelParse, traverse, loadPublicScript, extractFunctions, FakeElement, fakeDocument, textOf };
