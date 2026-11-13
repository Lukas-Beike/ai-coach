import { relative, resolve, sep } from "node:path";

// The modern-web-guidance CLI at the version package.json pins (lockfile hash),
// with telemetry and file logging off and only its read-only commands: it never
// installs a skill globally, and legacy-scan reads only public/ (#2633).
const ALLOWED = new Set(["search", "retrieve", "legacy-scan"]);
const [command, target] = process.argv.slice(2);

const outsidePublic = (path) => {
  const rest = relative(resolve("public"), resolve(path));
  return rest === ".." || rest.startsWith(`..${sep}`) || resolve(rest) === rest;
};
if (!ALLOWED.has(command) || (command === "legacy-scan" && (!target || outsidePublic(target)))) {
  console.error(`npm run modern-web -- <${[...ALLOWED].join("|")}> ...; legacy-scan takes a path in public/`);
  process.exit(2);
}
process.env.DISABLE_TELEMETRY = "1";
delete process.env.ENABLE_FILE_LOGGING;
delete process.env.MODERN_WEB_LOG_DIR;
await import("../node_modules/modern-web-guidance/skills/modern-web-guidance/modern-web.mjs");
