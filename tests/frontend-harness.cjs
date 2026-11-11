// Shared harness for the frontend unit tests: run public scripts in a vm context, pull named
// functions out of a script by AST (position in the file does not matter), and a minimal fake DOM.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { babelParse, traverse } = require("../node_modules/playwright/lib/transform/babelBundle.js"); // NOSONAR: issue #2090 asks for the Babel parser Playwright bundles; no other parser is installed.

function readPublic(file) {
  return fs.readFileSync(path.join(__dirname, "../public", file), "utf8").replaceAll("\r\n", "\n");
}

// `globals` is a plain object of sandbox globals (contextified in place, so a test may keep
// reaching it), or an existing vm context to run into.
function contextFor(globals) {
  return vm.isContext(globals) ? globals : vm.createContext(globals);
}

// Runs whole public files (one name or a list, in order) and returns the context.
function loadPublicScript(files, globals = {}) {
  const context = contextFor(globals);
  for (const file of [files].flat()) new vm.Script(readPublic(file), { filename: file }).runInContext(context); // NOSONAR: test-only, runs the repository's own public/ files.
  return context;
}

// Runs only the named function declarations or consts of a public file (top level, or directly
// inside a wrapping IIFE) and publishes each name as a property of the returned context.
function extractFunctions(file, names, globals = {}) {
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

class FakeElement {
  constructor(tag = "div") {
    Object.assign(this, { tag, tagName: tag.toUpperCase(), children: [], attributes: {}, dataset: {}, style: {}, listeners: {}, className: "", textContent: "", value: "", title: "", disabled: false });
    this.classList = { add: (...names) => { this.className = [this.className, ...names].filter(Boolean).join(" "); } };
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  focus() { this.focused = true; }
  fire(type, event = {}) { return this.listeners[type]({ preventDefault() {}, ...event }); }
}

// querySelector hands out one element per selector, kept in `nodes`.
function fakeDocument() {
  const nodes = new Map();
  return {
    nodes,
    createElement: (tag) => new FakeElement(tag),
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, new FakeElement());
      return nodes.get(selector);
    },
  };
}

module.exports = { loadPublicScript, extractFunctions, FakeElement, fakeDocument };
