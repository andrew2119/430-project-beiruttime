import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  resolve:{alias:{'@':fileURLToPath(new URL('../..',import.meta.url)),
    '@contracts':fileURLToPath(new URL('../../../packages',import.meta.url))}},
  test:{include:['features/counteroffers/*.test.ts','features/counteroffers/*.test.tsx'],maxWorkers:1},
  esbuild:{jsx:'automatic'},
});
