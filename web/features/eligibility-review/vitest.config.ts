import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  root: fileURLToPath(new URL('../..', import.meta.url)),
  esbuild: { jsx: 'automatic' },
  resolve: { dedupe:['react','react-dom'], alias: {
    '@': fileURLToPath(new URL('../..', import.meta.url)),
    '@contracts': fileURLToPath(new URL('../../../../packages', import.meta.url)),
  } },
  test: { include: ['../tests/lanes/L20/C16/*.test.tsx'], maxWorkers: 1 },
});
