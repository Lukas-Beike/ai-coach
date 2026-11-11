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
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const VIEWS = ["coach", "plan", "analysis", "nutrition", "more"];
export const WIDTHS = { phone: { width: 412, height: 915 }, desktop: { width: 1280, height: 900 } };

export function outsideRepo(target) {
  const resolved = path.resolve(target);
  const relative = path.relative(ROOT, resolved);
  if (!relative || (!relative.startsWith("..") && !path.isAbsolute(relative))) {
    throw new Error("the output directory must stay outside the repository");
  }
  return resolved;
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
  return { cache, assetVersions: [...new Set(versions)].sort() };
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
  const result = { loadMs: {}, errors: {}, calendar: {}, marks: null };
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
      const shot = (label) => page.screenshot({ path: path.join(outDir, `${name}-${label}.png`), fullPage: false });
      for (const route of VIEWS) {
        const before = errors.length;
        result.loadMs[`${name} ${route}`] = await rendered(page, route);
        await shot(route);
        result.errors[`${name} ${route}`] = errors.length - before;
        if (route === "plan") result.calendar[name] = await walkCalendar(page, shot);
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
      result.logout = { ...(result.logout || {}), [name]: logout };
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
    lines.push(`${errors ? "FAIL" : "ok"} ${key} ${ms} ms${errors ? `, ${errors} error(s)` : ""}`);
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
    outDir = outsideRepo(values["out-dir"]);
    password = fs.readFileSync(values["password-file"], "utf8").trim();
    if (!password) throw new Error("the secret file is empty");
  } catch (error) {
    console.log(`FAIL ${error.code === "ENOENT" ? "cannot read the secret file" : error.message}`);
    return 2;
  }
  fs.mkdirSync(outDir, { recursive: true });
  const previous = values.compare ? JSON.parse(fs.readFileSync(values.compare, "utf8")) : null;
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
  main().then((code) => { process.exitCode = code; });
}
