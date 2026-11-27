import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  root:fileURLToPath(new URL('../..',import.meta.url)),
  esbuild:{jsx:'automatic'},
  resolve:{alias:{'@':fileURLToPath(new URL('../..',import.meta.url))}},
  test:{include:['features/brand-decisions/*.test.ts'],maxWorkers:2},
});
