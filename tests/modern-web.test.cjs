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
  assert.equal(locked.resolved, `https://registry.npmjs.org/modern-web-guidance/-/modern-web-guidance-${pinned}.tgz`);
  assert.match(locked.integrity, /^sha512-[A-Za-z0-9+/]{86}==$/);
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
