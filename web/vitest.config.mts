import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Logic only, wherever it lives. Components are exercised through the running
// app instead, where the App Router boundaries and the streaming reader are
// real; a jsdom copy of them would test the mock. A pure function that happens
// to sit in a component file is still logic, so the glob covers src rather
// than src/lib.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
