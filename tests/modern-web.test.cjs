const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ROOT = path.join(__dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");

test("modern-web-guidance runs pinned, with telemetry off, and only read-only commands (#2633)", () => {
  const manifest = JSON.parse(read("package.json"));
  const pinned = manifest.devDependencies["modern-web-guidance"];
  assert.match(pinned, /^\d+\.\d+\.\d+$/);
  const locked = JSON.parse(read("package-lock.json")).packages["node_modules/modern-web-guidance"];
  assert.equal(locked.version, pinned);
  assert.match(locked.integrity, /^sha512-/);
  assert.equal(manifest.scripts["modern-web"], "node scripts/modern_web.mjs");
  const wrapper = read("scripts/modern_web.mjs");
  const telemetry = wrapper.indexOf('process.env.DISABLE_TELEMETRY = "1";');
  assert.ok(telemetry > 0 && telemetry < wrapper.indexOf("await import("));
  // No other entry point may call the CLI without the wrapper.
  const skill = read(".agents/skills/pacecraft-modern-web/SKILL.md");
  assert.doesNotMatch(skill, /npx|@latest|install -g/);
  const refused = spawnSync(process.execPath, [path.join(ROOT, "scripts", "modern_web.mjs"), "install"], { encoding: "utf8" });
  assert.equal(refused.status, 2);
});
