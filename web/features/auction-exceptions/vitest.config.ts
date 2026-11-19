import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  root: fileURLToPath(new URL('../..', import.meta.url)),
  esbuild: { jsx: 'automatic' },
  resolve: { alias: { '@': fileURLToPath(new URL('../..', import.meta.url)) } },
  test: { include: ['features/auction-exceptions/**/*.test.ts', 'features/auction-exceptions/**/*.test.tsx'], maxWorkers: 1 },
});
