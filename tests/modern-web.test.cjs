const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
// Loading the harness checks the install first, so a stale one names npm ci, not an ENOENT.
const { staleInstall } = require("./frontend-harness.cjs");

const ROOT = path.join(__dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
// Updated by hand only (athlete, #2633): a new version changes this hash too.
const INTEGRITY = "sha512-vafIZwC8AS6QjM2yyoflZbnc7n3/TVOMLbEMRdPTwcFy0f9/Tq8s5rJQ8UIqRt2KPl9ixravyaMR4nTGuUrcmg==";

test("modern-web-guidance runs pinned, with telemetry off, and only read-only commands (#2633)", () => {
  const manifest = JSON.parse(read("package.json"));
  const pinned = manifest.devDependencies["modern-web-guidance"];
  assert.match(pinned, /^\d+\.\d+\.\d+$/);
  const locked = JSON.parse(read("package-lock.json")).packages["node_modules/modern-web-guidance"];
  assert.equal(locked.version, pinned);
  assert.equal(locked.resolved, `https://registry.npmjs.org/modern-web-guidance/-/modern-web-guidance-${pinned}.tgz`);
  assert.equal(locked.integrity, INTEGRITY);
  assert.equal(manifest.scripts["modern-web"], "node scripts/modern_web.mjs");
  const wrapper = read("scripts/modern_web.mjs");
  const telemetry = wrapper.indexOf('process.env.DISABLE_TELEMETRY = "1";');
  assert.ok(telemetry > 0 && telemetry < wrapper.indexOf("await import("));
  // The installed CLI still honours that switch, so an update cannot drop it unseen.
  const cli = read("node_modules/modern-web-guidance/skills/modern-web-guidance/modern-web.mjs");
  assert.match(cli, /env\.DISABLE_TELEMETRY\?\.toLowerCase\(\);\s+if \(optOutSetting === "1"/);
  // The skill and the frontend instructions call the CLI only through the wrapper.
  for (const file of [".agents/skills/pacecraft-modern-web/SKILL.md", "public/AGENTS.md"]) {
    assert.doesNotMatch(read(file), /npx|@latest|install -g/, file);
  }
  const deny = JSON.parse(read(".claude/settings.json")).permissions.deny;
  assert.ok(deny.includes("Bash(npx *modern-web-guidance*)"));
  for (const args of [["install"], ["legacy-scan", "data"], ["legacy-scan", ".."], ["legacy-scan"]]) {
    const refused = spawnSync(process.execPath, [path.join(ROOT, "scripts", "modern_web.mjs"), ...args], { cwd: ROOT, encoding: "utf8" });
    assert.equal(refused.status, 2, args.join(" "));
  }
});

test("a node_modules older than package-lock.json is named with its fix before any test runs (#2690)", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "pacecraft-install-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const write = (relative, packages) => {
    fs.mkdirSync(path.dirname(path.join(root, relative)), { recursive: true });
    fs.writeFileSync(path.join(root, relative), JSON.stringify({ packages }));
  };
  const lock = { "": {}, "node_modules/a": { version: "2.0.0" }, "node_modules/a/node_modules/b": { version: "1.0.0" }, "node_modules/c": { version: "1.0.0", optional: true } };
  write("package-lock.json", lock);
  assert.deepEqual(staleInstall(root), ["node_modules/a", "node_modules/a/node_modules/b"]);
  write("node_modules/.package-lock.json", { ...lock, "node_modules/a": { version: "1.0.0" }, "node_modules/c": undefined });
  assert.deepEqual(staleInstall(root), ["node_modules/a"]);
  write("node_modules/.package-lock.json", { ...lock, "node_modules/c": undefined });
  assert.deepEqual(staleInstall(root), []);
});
