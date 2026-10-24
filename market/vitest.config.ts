import { defineConfig } from "vitest/config";

// Rules tests only; the SpacetimeDB module has its own vitest config in spacetimedb/.
export default defineConfig({ test: { include: ["rules/**/*.test.ts"] } });
