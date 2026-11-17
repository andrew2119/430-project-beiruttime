import { defineConfig } from 'vitest/config';
export default defineConfig({
  esbuild: { jsx: 'automatic' },
  test: { include: ['features/brand-jobs/*.test.tsx'], maxWorkers: 1 },
});
