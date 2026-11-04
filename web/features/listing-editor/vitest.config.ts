import { defineConfig } from "vitest/config";
export default defineConfig({
  esbuild: { jsx: 'automatic' },
  resolve: { alias: { "@": new URL("../../", import.meta.url).pathname } },
  test: { include: ["features/listing-editor/*.test.ts"], maxWorkers: 1 },
});
