const test = require("node:test");
const assert = require("node:assert/strict");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const SCRIPT = path.join(__dirname, "..", "scripts", "ui_walk.mjs");
const load = () => import(require("node:url").pathToFileURL(SCRIPT).href);

test("ui walk keeps files in the temp directory and needs an http(s) address", async () => {
  const walk = await load();
  assert.throws(() => walk.scratchPath(path.join(__dirname, "..", "shots")), /system temp directory/);
  assert.throws(() => walk.scratchPath(path.join(__dirname, "..")), /system temp directory/);
  assert.throws(() => walk.scratchPath(path.join(os.tmpdir(), "..", "elsewhere")), /system temp directory/);
  assert.equal(walk.scratchPath(path.join(os.tmpdir(), "walk")), path.resolve(os.tmpdir(), "walk"));
  assert.equal(walk.baseUrl("https://app.example.test:8090/some/path"), "https://app.example.test:8090");
  assert.throws(() => walk.baseUrl("file:///etc/passwd"), /http\(s\) URL/);
});

test("ui walk reads the stamped cache name and asset versions", async () => {
  const walk = await load();
  const marks = walk.releaseMarks(
    'const CACHE = "pacecraft-abc123";\nconst ASSETS = [];',
    '<script src="app.js?v=b2"></script><link href="app.css?v=a1"><script src="api.js?v=b2"></script>',
  );
  assert.deepEqual(marks, { cache: "pacecraft-abc123", assetVersions: ["a1", "b2"] });
  assert.deepEqual(walk.releaseMarks("", ""), { cache: null, assetVersions: [] });
});

test("ui walk reports errors per view and compares load times with the previous walk", async () => {
  const walk = await load();
  const result = {
    loadMs: { "phone coach": 800, "phone plan": 1200 },
    errors: { "phone coach": 0, "phone plan": 2 },
    calendar: { phone: ["month", "next week"] },
    marks: { cache: "pacecraft-new", assetVersions: ["a"] },
    logout: { phone: 200 },
  };
  const lines = walk.reportLines(result);
  assert.ok(lines.includes("ok phone coach 800 ms"));
  assert.ok(lines.includes("FAIL phone plan 1200 ms, 2 error(s)"));
  assert.ok(lines.includes("info calendar phone: month, next week"));
  assert.ok(lines.includes("ok logout phone 200"));
  const compared = walk.compareLines(result, { marks: { cache: "pacecraft-old" }, loadMs: { "phone coach": 700 } });
  assert.deepEqual(compared, ["info service-worker cache changed since the previous walk", "info load phone coach 800 ms (was 700 ms)"]);
  assert.deepEqual(walk.compareLines(result, null), []);
});

test("ui walk refuses missing arguments and an unreadable secret file without a browser", () => {
  const run = (...args) => spawnSync(process.execPath, [SCRIPT, ...args], { encoding: "utf8" });
  let done = run("--url", "http://127.0.0.1:9");
  assert.equal(done.status, 2);
  assert.match(done.stdout, /required/);
  done = run("--url", "http://127.0.0.1:9", "--password-file", path.join(os.tmpdir(), "missing-secret-file"), "--out-dir", path.join(os.tmpdir(), "walk"));
  assert.equal(done.status, 2);
  assert.match(done.stdout, /cannot read the secret file/);
});
