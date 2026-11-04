import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  root: fileURLToPath(new URL('../..', import.meta.url)),
  resolve: {alias:{'@':fileURLToPath(new URL('../..',import.meta.url))}},
  test:{include:['features/brand-options/*.test.ts'],maxWorkers:2},
});
