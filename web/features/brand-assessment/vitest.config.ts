import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  root: fileURLToPath(new URL('../..', import.meta.url)),
  esbuild: { jsx: 'automatic' },
  resolve: { alias: {
    '@': fileURLToPath(new URL('../..', import.meta.url)),
    'vitest': fileURLToPath(new URL('../../node_modules/vitest/dist/index.js', import.meta.url)),
    'react-dom/server': fileURLToPath(new URL('../../node_modules/react-dom/server.node.js', import.meta.url)),
    'react/jsx-dev-runtime': fileURLToPath(new URL('../../node_modules/react/jsx-dev-runtime.js', import.meta.url)),
    'react/jsx-runtime': fileURLToPath(new URL('../../node_modules/react/jsx-runtime.js', import.meta.url)),
  } },
  test: { include: ['../tests/lanes/L17/C08/*.test.tsx'], maxWorkers: 1 },
});
