import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  esbuild: {jsx: 'automatic'},
  resolve: {alias: {
    '@': fileURLToPath(new URL('../..', import.meta.url)),
    '@contracts': fileURLToPath(new URL('../../../packages', import.meta.url)),
  }},
  test: {include: ['features/external-sign-in/*.test.ts', 'features/external-sign-in/*.test.tsx'], maxWorkers: 1},
});
