import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import { defineConfig } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["dist", "public/data", "src/contract"] },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [reactHooks.configs.flat["recommended-latest"]],
    languageOptions: { globals: globals.browser },
  },
  {
    files: ["scripts/**/*.mjs"],
    languageOptions: { globals: globals.node },
  },
  // ADR-001: the simulation engine is pure and seeded.
  {
    files: ["src/sim/**/*.ts"],
    rules: {
      "no-restricted-properties": [
        "error",
        { object: "Math", property: "random", message: "Use the seeded PRNG (ADR-001)." },
      ],
      "no-restricted-globals": [
        "error",
        ...["window", "document", "self", "fetch", "localStorage", "postMessage"].map((name) => ({
          name,
          message: "src/sim is pure: no DOM, network or worker globals (ADR-001).",
        })),
      ],
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/app/**", "**/worker/**", "react", "react-dom"],
              message: "src/sim must not depend on UI or worker code (ADR-001).",
            },
          ],
        },
      ],
    },
  },
);
