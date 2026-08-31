import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Only the logic layer is covered here. Components are exercised through the
// running app instead, where the App Router boundaries and the streaming
// reader are real; a jsdom copy of them would test the mock.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    include: ["src/lib/**/*.test.ts"],
    environment: "node",
  },
});
