import { resolve } from "node:path";

// OpenSpec can migrate its global profile during init/update; keep it local.
process.env.XDG_CONFIG_HOME = resolve(".openspec-local/config");
process.env.XDG_DATA_HOME = resolve(".openspec-local/data");
process.env.OPENSPEC_TELEMETRY = "0";
await import("../node_modules/@fission-ai/openspec/bin/openspec.js");
