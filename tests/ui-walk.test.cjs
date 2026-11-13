const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
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
  // The password file may come from the T3 secret folder, read only (#2527).
  const t3 = path.join(os.homedir(), "t3-folder-for-a-test", "secrets");
  assert.equal(walk.secretPath(path.join(t3, "app-password"), t3), path.join(t3, "app-password"));
  assert.equal(walk.secretPath(path.join(os.tmpdir(), "secret"), t3), path.resolve(os.tmpdir(), "secret"));
  assert.throws(() => walk.secretPath(path.join(__dirname, "..", ".env"), t3), /T3 secret folder/);
  assert.throws(() => walk.secretPath(path.join(t3, "..", "other"), t3), /T3 secret folder/);
  assert.throws(() => walk.secretPath("app-password", t3), /must be absolute/);
  const root = path.resolve(__dirname, "..");
  assert.throws(() => walk.secretPath(path.join(root, ".env"), path.dirname(root)), /T3 secret folder/);
  // A link in the temp directory that leads into the repository is refused.
  const linkDir = fs.mkdtempSync(path.join(os.tmpdir(), "walk-link-"));
  const link = path.join(linkDir, "checkout");
  fs.symlinkSync(root, link, "junction");
  try {
    assert.throws(() => walk.secretPath(path.join(link, "package.json"), t3), /T3 secret folder/);
    // The scratch guard follows the link too, also for a directory not created yet (#2615).
    assert.throws(() => walk.scratchPath(path.join(link, "shots")), /system temp directory/);
    assert.throws(() => walk.scratchPath(path.join(link, "new", "deeper")), /system temp directory/);
    assert.equal(walk.scratchPath(path.join(linkDir, "shots")), path.join(linkDir, "shots"));
    // A link that leaves the temp directory without entering the repository, and a
    // dangling link, are refused as well; the drive letter's case does not matter.
    const away = path.join(linkDir, "home");
    fs.symlinkSync(os.homedir(), away, "junction");
    const dangling = path.join(linkDir, "dangling");
    fs.symlinkSync(path.join(linkDir, "missing"), dangling, "junction");
    try {
      assert.throws(() => walk.scratchPath(path.join(away, "shots")), /system temp directory/);
      assert.throws(() => walk.scratchPath(path.join(dangling, "shots")), /system temp directory/);
    } finally {
      fs.unlinkSync(away);
      fs.unlinkSync(dangling);
    }
    const other = path.join(linkDir, "shots");
    const swapped = other[0] === other[0].toLowerCase() ? other[0].toUpperCase() : other[0].toLowerCase();
    assert.equal(walk.scratchPath(swapped + other.slice(1)).toLowerCase(), other.toLowerCase());
  } finally {
    // Remove the link itself first so cleanup never descends into the checkout.
    fs.unlinkSync(link);
    fs.rmdirSync(linkDir);
  }
  assert.throws(() => walk.scratchPath(path.join(t3, "shots")), /system temp directory/);
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
    errors: { "phone login": 1, "phone coach": 0, "phone plan": 2, "phone other": 0 },
    calendar: { phone: ["month", "next week"] },
    marks: { cache: "pacecraft-new", assetVersions: ["a"] },
    logout: { phone: 200 },
    measure: walk.LOAD_MEASURE,
    notReady: { "phone coach": ["GET /api/performance"], "phone more": [] },
  };
  const lines = walk.reportLines(result);
  // A view that never became ready names the requests of that view still open (#2581).
  assert.ok(lines.includes("info phone coach not ready within 15 s; still loading: GET /api/performance"));
  assert.ok(lines.includes("info phone more not ready within 15 s; still loading: only a loading marker"));
  assert.ok(!lines.some((line) => line.startsWith("info phone plan not ready")));
  // Only method and path are kept; other hosts keep their origin, blob and data URLs are skipped.
  assert.equal(walk.requestKey("GET", "https://app.test/api/plan?local=1", "https://app.test"), "GET /api/plan");
  assert.equal(walk.requestKey("GET", "https://tiles.test/a/b.png?k=1", "https://app.test"), "GET https://tiles.test/a/b.png");
  assert.equal(walk.requestKey("GET", "blob:https://app.test/1234", "https://app.test"), null);
  // A walk measured another way is not compared.
  assert.deepEqual(walk.compareLines(result, { marks: { cache: "pacecraft-new" }, loadMs: { "phone coach": 15000 } }), ["info service-worker cache unchanged since the previous walk", "info load times not compared: the previous walk measured them differently"]);
  assert.ok(lines.includes("ok phone coach 800 ms"));
  assert.ok(lines.includes("FAIL phone plan 1200 ms, 2 error(s)"));
  assert.ok(lines.includes("FAIL phone login 1 error(s)"));
  assert.ok(!lines.some((line) => line.includes("phone other")));
  assert.ok(lines.includes("info calendar phone: month, next week"));
  assert.ok(lines.includes("ok logout phone 200"));
  const compared = walk.compareLines(result, { measure: walk.LOAD_MEASURE, marks: { cache: "pacecraft-old" }, loadMs: { "phone coach": 700 } });
  assert.deepEqual(compared, ["info service-worker cache changed since the previous walk", "info load phone coach 800 ms (was 700 ms)"]);
  assert.deepEqual(walk.compareLines(result, null), []);
});

test("ui walk refuses missing arguments and an unreadable secret file without a browser", () => {
  const run = (...args) => spawnSync(process.execPath, [SCRIPT, ...args], { encoding: "utf8" });
  let done = run("--url", "http://127.0.0.1:9");
  assert.equal(done.status, 2);
  assert.match(done.stdout, /required/);
  // A malformed address keeps its own message, not the secret-file one.
  done = run("--url", "not a url", "--password-file", path.join(os.tmpdir(), "missing-secret-file"), "--out-dir", path.join(os.tmpdir(), "walk"));
  assert.equal(done.status, 2);
  assert.doesNotMatch(done.stdout, /secret file/);
  done = run("--url", "http://127.0.0.1:9", "--password-file", path.join(os.tmpdir(), "missing-secret-file"), "--out-dir", path.join(os.tmpdir(), "walk"));
  assert.equal(done.status, 2);
  assert.match(done.stdout, /cannot read the secret file/);
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "walk-test-"));
  const secret = path.join(scratch, "secret");
  fs.writeFileSync(secret, "fake-login-value");
  const notJson = path.join(scratch, "previous.json");
  fs.writeFileSync(notJson, "fake-login-value is not JSON");
  done = run("--url", "http://127.0.0.1:9", "--password-file", secret, "--out-dir", path.join(scratch, "walk"), "--compare", notJson);
  fs.rmSync(scratch, { recursive: true, force: true });
  assert.equal(done.status, 2);
  assert.match(done.stdout, /cannot read the previous walk/);
  assert.doesNotMatch(done.stdout, /fake-login-value/);
  // An out-dir that cannot be created (a file already holds its path) exits 2 without a stack trace (#2661).
  const blocked = fs.mkdtempSync(path.join(os.tmpdir(), "walk-blocked-"));
  fs.writeFileSync(path.join(blocked, "file"), "x");
  fs.writeFileSync(path.join(blocked, "secret"), "fake-login-value");
  done = run("--url", "http://127.0.0.1:9", "--password-file", path.join(blocked, "secret"), "--out-dir", path.join(blocked, "file"));
  fs.rmSync(blocked, { recursive: true, force: true });
  assert.equal(done.status, 2);
  assert.match(done.stdout, /^FAIL cannot create the out-dir$/m);
  assert.doesNotMatch(done.stderr, /at .*ui_walk/);
});

test("ui walk replaces a link or hard link at a fixed name instead of following it (#2661)", async () => {
  const walk = await load();
  const outDir = fs.mkdtempSync(path.join(os.tmpdir(), "walk-out-"));
  const victimDir = fs.mkdtempSync(path.join(os.tmpdir(), "walk-victim-"));
  const victim = path.join(victimDir, "kept.txt");
  try {
    fs.writeFileSync(victim, "original");
    fs.linkSync(victim, path.join(outDir, "ui-walk.json"));
    let symlinked = true;
    try {
      fs.symlinkSync(victim, path.join(outDir, "mobile-coach.png"), "file");
    } catch {
      symlinked = false; // Windows without the symlink privilege: the hard link still covers it.
    }
    walk.writeFresh(outDir, "ui-walk.json", "{}");
    if (symlinked) walk.writeFresh(outDir, "mobile-coach.png", "png");
    assert.equal(fs.readFileSync(victim, "utf8"), "original");
    assert.equal(fs.readFileSync(path.join(outDir, "ui-walk.json"), "utf8"), "{}");
    assert.equal(fs.lstatSync(path.join(outDir, "ui-walk.json")).nlink, 1);
    if (symlinked) assert.equal(fs.lstatSync(path.join(outDir, "mobile-coach.png")).isSymbolicLink(), false);
    // An out-dir outside the temp directory is refused before any write.
    assert.throws(() => walk.writeFresh(path.join(__dirname, ".."), "ui-walk.json", "{}"), /system temp directory/);
  } finally {
    fs.rmSync(outDir, { recursive: true, force: true });
    fs.rmSync(victimDir, { recursive: true, force: true });
  }
});
