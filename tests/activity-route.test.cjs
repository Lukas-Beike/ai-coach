const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, fakeDocument, FakeElement } = require("./frontend-harness.cjs");

function text(item) {
  if (typeof item === "string") return item;
  return [item.textContent, ...item.children.map(text)].join("");
}

function loadRenderRoute() {
  const document = fakeDocument();
  return extractFunctions("activity-details.js", ["renderRoute"], { document }).renderRoute;
}

const ROUTE = { label: "Hausrunde", repeat_index: 5, repeat_count: 6, route_id: "r3" };

test("the route shows its label and visit with a rename action", () => {
  const content = new FakeElement("div");
  loadRenderRoute()(ROUTE, async () => ({}), content);
  const [line] = content.children;
  assert.equal(text(line.children[0]) + text(line.children[1]), "Hausrunde, 5. Mal Umbenennen");
  assert.equal(line.children[1].tag, "button");
});

test("a session without a route renders nothing", () => {
  const content = new FakeElement("div");
  loadRenderRoute()(undefined, async () => ({}), content);
  assert.equal(content.children.length, 0);
});

test("renaming posts the route id and name, then shows the new label", async () => {
  const content = new FakeElement("div");
  const calls = [];
  const api = async (url, options) => { calls.push([url, JSON.parse(options.body), options.method]); return { label: "Seerunde" }; };
  loadRenderRoute()(ROUTE, api, content);
  const [line] = content.children;
  line.children[1].fire("click");
  const form = line.children[0];
  assert.equal(form.tag, "form");
  const input = form.children.find((child) => child.tag === "input");
  assert.equal(input.value, "Hausrunde");
  assert.equal(input.maxLength, 60);
  input.value = "Seerunde";
  await form.fire("submit");
  assert.deepEqual(calls, [["/api/routes/rename", { route_id: "r3", name: "Seerunde" }, "POST"]]);
  assert.equal(text(line.children[0]), "Seerunde, 5. Mal ");
});

test("a refused name stays in the form with the message", async () => {
  const content = new FakeElement("div");
  const api = async () => { throw new Error("Der Name ist ungültig."); };
  loadRenderRoute()(ROUTE, api, content);
  const [line] = content.children;
  line.children[1].fire("click");
  const form = line.children[0];
  await form.fire("submit");
  assert.equal(line.children[0], form);
  assert.match(text(form), /Der Name ist ungültig\./);
});
