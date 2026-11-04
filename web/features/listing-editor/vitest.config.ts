import { defineConfig } from "vitest/config";
export default defineConfig({
  test: { include: ["features/listing-editor/*.test.ts"], maxWorkers: 1 },
});
