import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  root: fileURLToPath(new URL('../..', import.meta.url)),
  esbuild: { jsx: 'automatic' },
  resolve: { dedupe: ['react', 'react-dom', '@tanstack/react-query'], alias: { '@': fileURLToPath(new URL('../..', import.meta.url)) } },
  test: { server: { deps: { external: [/^react(?:-dom)?(?:\/.*)?$/] } }, include: ['features/discovery/**/*.test.ts', 'features/live-bids/**/*.test.ts', '../tests/lanes/L15/DISCOVERY/*.test.ts'], maxWorkers: 1 },
});
