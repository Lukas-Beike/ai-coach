const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/views.js"), "utf8");
const end = source.indexOf("const CALENDAR_DISPLAY_MAX_WEEKS");

function markdownToHtml(markdown) {
  assert.ok(end > 0);
  const context = vm.createContext({});
  vm.runInContext(source.slice(0, end), context);
  return vm.runInContext("markdownToHtml", context)(markdown);
}

test("a 2x2 markdown table renders a labelled scroll region with header and body cells", () => {
  const html = markdownToHtml("| Name | Wert |\n| --- | :---: |\n| A | 1 |\n| B | 2 |");
  assert.match(html, /^<div class="markdown-table" tabindex="0" role="region" aria-label="Tabelle"><table>/);
  assert.equal(html.match(/<th scope="col">/g).length, 2);
  assert.equal(html.match(/<td>/g).length, 4);
  assert.ok(html.includes("<th scope=\"col\">Name</th><th scope=\"col\">Wert</th>"));
  assert.ok(html.includes("<tr><td>B</td><td>2</td></tr>"));
});

test("table cells are escaped and never pass raw HTML through", () => {
  const html = markdownToHtml("| Feld |\n| --- |\n| <script>alert(1)</script> |");
  assert.ok(html.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.ok(!html.includes("<script>"));
});

test("short rows are padded and extra cells beyond the header count are dropped", () => {
  const html = markdownToHtml("| a | b |\n| - | - |\n| 1 |\n| 1 | 2 | 3 |");
  assert.ok(html.includes("<tr><td>1</td><td></td></tr>"));
  assert.ok(html.includes("<tr><td>1</td><td>2</td></tr>"));
  assert.ok(!html.includes(">3<"));
});

test("a table block flushes the preceding paragraph before rendering", () => {
  const html = markdownToHtml("Einleitung\n| a | b |\n| - | - |\n| 1 | 2 |");
  assert.ok(html.startsWith("<p>Einleitung</p><div class=\"markdown-table\""));
});

test("a pipe line without a separator stays a paragraph", () => {
  const html = markdownToHtml("| nur eine Zeile |\n| zweite |");
  assert.equal(html, "<p>| nur eine Zeile |<br>| zweite |</p>");
  assert.ok(!html.includes("<table"));
});

test("a table inside a code fence is rendered as code, not as a table", () => {
  const html = markdownToHtml("```\n| a | b |\n| --- | --- |\n```");
  assert.equal(html, "<pre><code>| a | b |\n| --- | --- |</code></pre>");
  assert.ok(!html.includes("<table"));
});
