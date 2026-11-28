import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  resolve: { alias: { '@': fileURLToPath(new URL('../../', import.meta.url)) } },
  esbuild: { jsx: 'automatic' },
  test: { include: ['features/transaction-reviews/**/*.test.tsx'], maxWorkers: 1 },
});
