// Headless read-only walk through the running app at phone and desktop width.
//
//   node scripts/ui_walk.mjs --url <app address> --password-file <secret file>
//     --out-dir <scratchpad dir> [--compare <previous ui-walk.json>]
//
// Logs in with the password read from the file (never printed or passed on a
// command line), opens each main view, switches the calendar between week and
// month and pages it, takes screenshots, measures time to rendered content,
// records the service-worker cache name and asset versions, and logs out.
// It presses no control that saves, syncs, deletes or sends. Exit 0 no error,
// 1 a view failed or logged errors, 2 bad input or login refused.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const VIEWS = ["coach", "plan", "analysis", "nutrition", "more"];
export const WIDTHS = { phone: { width: 412, height: 915 }, desktop: { width: 1280, height: 900 } };

// The password file is only read: the temp directory or the folder where a T3
// secret request delivers files, never the repository (#2527).
export const T3_SECRETS = path.join(os.homedir(), ".t3", "userdata", "secrets");
// Links are followed and Windows paths compare without case, as in prod_client.py.
// A path that does not exist yet resolves through its nearest existing parent, so
// a new directory under a link is judged by where the link leads (#2615).
const realPath = (target) => {
  const resolved = path.resolve(target);
  try {
    return fs.realpathSync.native(resolved);
  } catch (error) {
    // Only a missing path resolves through its parent; a dangling link, a loop or an
    // unreadable path resolves to nothing, which no guard accepts.
    if (error.code !== "ENOENT" || fs.lstatSync(resolved, { throwIfNoEntry: false })) return "";
    const parent = path.dirname(resolved);
    return parent === resolved ? resolved : path.join(realPath(parent), path.basename(resolved));
  }
};
const folded = (target) => (process.platform === "win32" ? target.toLowerCase() : target) + path.sep;

// The path as given and the file a link leads to must both lie in one of the
// roots and outside the repository; a path that does not exist yet is judged
// through its nearest existing parent (#2615).
function confined(target, roots, refused) {
  const resolved = path.resolve(os.tmpdir(), String(target));
  const repository = [folded(ROOT), folded(realPath(ROOT))];
  const checks = [
    [resolved, roots.map((root) => path.resolve(root))],
    [realPath(resolved), roots.map(realPath)],
  ];
  for (const [candidate, bases] of checks) {
    const where = folded(candidate);
    if (repository.some((repo) => where.startsWith(repo)) || !bases.some((base) => where.startsWith(folded(base)))) {
      throw refused;
    }
  }
  return resolved;
}

// Every file the walk reads or writes lives in the system temp directory (the
// session scratchpad), never in the repository or anywhere else a path could reach.
export function scratchPath(target) {
  return confined(target, [os.tmpdir()], new Error("files must be in the system temp directory"));
}

export function secretPath(target, secrets = T3_SECRETS) {
  if (!path.isAbsolute(String(target))) throw new Error("the password file path must be absolute");
  const refused = new Error("the password file must be in the system temp directory or the T3 secret folder");
  return confined(target, [os.tmpdir(), secrets], refused);
}

export function baseUrl(text) {
  const url = new URL(text);
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("the app address must be an http(s) URL");
  return url.origin;
}

// The cache name and asset versions are content hashes the server stamps.
export function releaseMarks(serviceWorker, indexHtml) {
  const cache = /const CACHE = "([^"]+)"/.exec(serviceWorker)?.[1] || null;
  const versions = [...indexHtml.matchAll(/\?v=([A-Za-z0-9_-]+)/g)].map((match) => match[1]);
  return { cache, assetVersions: [...new Set(versions)].sort((a, b) => a.localeCompare(b)) };
}

export function compareLines(current, previous) {
  const lines = [];
  if (!previous) return lines;
  const same = current.marks.cache === previous.marks?.cache;
  lines.push(`info service-worker cache ${same ? "unchanged" : "changed"} since the previous walk`);
  for (const [key, ms] of Object.entries(current.loadMs)) {
    const before = previous.loadMs?.[key];
    if (typeof before === "number") lines.push(`info load ${key} ${ms} ms (was ${before} ms)`);
  }
  return lines;
}

async function rendered(page, route) {
  const started = Date.now();
  await page.evaluate(async (next) => {
    const done = new Promise((resolve) => {
      document.addEventListener("app:route-rendered", resolve, { once: true });
      setTimeout(resolve, 15000);
    });
    if (globalThis.location.hash === `#${next}`) globalThis.location.hash = "";
    globalThis.location.hash = next;
    await done;
  }, route);
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  return Date.now() - started;
}

// Views render asynchronously: wait briefly for a visible control.
async function clickIfThere(locator) {
  const target = locator.filter({ visible: true }).first();
  try {
    await target.waitFor({ state: "visible", timeout: 3000 });
  } catch {
    return false;
  }
  await target.click();
  return true;
}

async function walkCalendar(page, shot) {
  const done = [];
  // Open a unit first: paging later may land on an empty week.
  if (await clickIfThere(page.locator(".planned-entry > summary"))) {
    await shot("plan-unit");
    done.push("unit opened");
  }
  if (await clickIfThere(page.locator('.planned-view-switch button[data-view="month"]'))) {
    await shot("plan-month");
    done.push("month");
    await clickIfThere(page.getByRole("button", { name: "Nächster Monat" }));
    await clickIfThere(page.locator('.planned-view-switch button[data-view="week"]'));
  }
  if (await clickIfThere(page.getByRole("button", { name: "Nächste Woche" }))) done.push("next week");
  if (await clickIfThere(page.getByRole("button", { name: "Vorherige Woche" }))) done.push("previous week");
  return done;
}

async function walk({ chromium, url, password, outDir }) {
  const result = { loadMs: {}, errors: {}, calendar: {}, marks: null, logout: {} };
  const browser = await chromium.launch();
  try {
    for (const [name, viewport] of Object.entries(WIDTHS)) {
      const context = await browser.newContext({ baseURL: url, viewport });
      const page = await context.newPage();
      const errors = [];
      page.on("console", (message) => message.type() === "error" && errors.push("console"));
      page.on("pageerror", () => errors.push("page"));
      page.on("response", (response) => response.status() >= 500 && errors.push(`http ${response.status()}`));
      await page.goto("/");
      await page.getByLabel("Passwort", { exact: true }).fill(password);
      await page.getByRole("button", { name: "Anmelden" }).click();
      await page.locator("#appShell").waitFor({ state: "visible", timeout: 30000 });
      // Every error counts against a step: login, a view (with its calendar walk), or the rest.
      result.errors[`${name} login`] = errors.length;
      let counted = errors.length;
      const shot = (label) => page.screenshot({ path: path.join(outDir, `${name}-${label}.png`), fullPage: false });
      for (const route of VIEWS) {
        result.loadMs[`${name} ${route}`] = await rendered(page, route);
        await shot(route);
        if (route === "plan") result.calendar[name] = await walkCalendar(page, shot);
        result.errors[`${name} ${route}`] = errors.length - counted;
        counted = errors.length;
      }
      if (!result.marks) {
        const serviceWorker = await (await page.request.get("/service-worker.js")).text();
        const indexHtml = await (await page.request.get("/")).text();
        result.marks = releaseMarks(serviceWorker, indexHtml);
      }
      const logout = await page.evaluate(async () => {
        const token = document.cookie.split("; ").find((item) => item.startsWith("ic_csrf="))?.slice(8) || "";
        const response = await fetch("/api/logout", { method: "POST", headers: { "X-CSRF-Token": decodeURIComponent(token), "Content-Type": "application/json" }, body: "{}" });
        return response.status;
      });
      result.logout[name] = logout;
      result.errors[`${name} other`] = errors.length - counted;
      await context.close();
    }
  } finally {
    await browser.close();
  }
  return result;
}

export function reportLines(result) {
  const lines = [];
  for (const [key, ms] of Object.entries(result.loadMs)) {
    const errors = result.errors[key];
    const suffix = errors ? ", " + errors + " error(s)" : "";
    lines.push(`${errors ? "FAIL" : "ok"} ${key} ${ms} ms${suffix}`);
  }
  for (const [key, errors] of Object.entries(result.errors)) {
    if (errors && !(key in result.loadMs)) lines.push(`FAIL ${key} ${errors} error(s)`);
  }
  for (const [name, steps] of Object.entries(result.calendar)) lines.push(`info calendar ${name}: ${steps.join(", ") || "no controls found"}`);
  lines.push(`info service-worker cache ${result.marks?.cache || "missing"}, ${result.marks?.assetVersions.length || 0} asset versions`);
  for (const [name, status] of Object.entries(result.logout || {})) lines.push(`${status === 200 ? "ok" : "FAIL"} logout ${name} ${status}`);
  return lines;
}

async function main() {
  const { values } = parseArgs({
    options: { url: { type: "string" }, "password-file": { type: "string" }, "out-dir": { type: "string" }, compare: { type: "string" } },
  });
  let url;
  let outDir;
  let password;
  try {
    if (!values.url || !values["password-file"] || !values["out-dir"]) throw new Error("--url, --password-file and --out-dir are required");
    url = baseUrl(values.url);
    outDir = scratchPath(values["out-dir"]);
    password = fs.readFileSync(secretPath(values["password-file"]), "utf8").trim();
    if (!password) throw new Error("the secret file is empty");
  } catch (error) {
    // A file-system error names the secret file's path; never print it.
    console.log(`FAIL ${error.syscall ? "cannot read the secret file" : error.message}`);
    return 2;
  }
  fs.mkdirSync(outDir, { recursive: true });
  let previous = null;
  try {
    previous = values.compare ? JSON.parse(fs.readFileSync(scratchPath(values.compare), "utf8")) : null;
  } catch {
    // The error text could quote the file's content; never print it.
    console.log("FAIL cannot read the previous walk");
    return 2;
  }
  const { chromium } = await import("@playwright/test");
  let result;
  try {
    result = await walk({ chromium, url, password, outDir });
  } catch (error) {
    console.log(`FAIL walk stopped (${error.name})`);
    return 2;
  }
  fs.writeFileSync(path.join(outDir, "ui-walk.json"), JSON.stringify(result, null, 2));
  const lines = [...reportLines(result), ...compareLines(result, previous)];
  for (const line of lines) console.log(line);
  return lines.some((line) => line.startsWith("FAIL")) ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  process.exitCode = await main();
}
