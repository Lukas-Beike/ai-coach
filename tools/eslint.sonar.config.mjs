// Sonar's own JavaScript rules for `tools/quality_baseline.py`; lints nothing else.
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// The pre-push hook checks a clean export of HEAD, which has no node_modules.
const modules =
  process.env.PACECRAFT_NODE_MODULES ||
  join(fileURLToPath(new URL("..", import.meta.url)), "node_modules");
const sonarjs = createRequire(join(modules, "_"))("eslint-plugin-sonarjs");

export default [
  {
    files: ["public/**/*.js"],
    plugins: { sonarjs },
    linterOptions: { reportUnusedDisableDirectives: "off" },
    languageOptions: { ecmaVersion: "latest", sourceType: "script" },
    rules: {
      "sonarjs/cognitive-complexity": ["error", 15],
      "sonarjs/no-nested-conditional": "error",
    },
  },
];
