// The modern-web-guidance CLI at the version package.json pins (lockfile hash),
// with telemetry off and only its read-only commands: it never installs a skill
// globally (#2633).
const ALLOWED = new Set(["search", "retrieve", "legacy-scan"]);

if (!ALLOWED.has(process.argv[2])) {
  console.error(`npm run modern-web -- <${[...ALLOWED].join("|")}> ...`);
  process.exit(2);
}
process.env.DISABLE_TELEMETRY = "1";
await import("../node_modules/modern-web-guidance/skills/modern-web-guidance/modern-web.mjs");
