import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  root: fileURLToPath(new URL('../..', import.meta.url)),
  esbuild: { jsx: 'automatic' },
  resolve: { alias: { '@': fileURLToPath(new URL('../..', import.meta.url)) } },
  test: { include: ['features/discovery/**/*.test.ts', 'features/live-bids/**/*.test.ts'], maxWorkers: 1 },
});
