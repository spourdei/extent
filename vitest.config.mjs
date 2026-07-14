import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    exclude: ["**/.next/**", "**/node_modules/**"],
    include: ["apps/web/test/**/*.test.ts"],
  },
});
