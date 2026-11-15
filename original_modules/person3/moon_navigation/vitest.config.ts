import { defineConfig } from "vitest/config";

// Separate from vite.config.ts (whose root is src/web) so tests run from the project root.
export default defineConfig({
  test: {
    root: ".",
    include: ["tests/**/*.test.ts"],
    environment: "node",
  },
});
