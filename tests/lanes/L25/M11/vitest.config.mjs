import { fileURLToPath } from 'node:url';
export default {
  esbuild: { jsx: 'automatic' },
  resolve: { alias: {
    'vitest': fileURLToPath(new URL('../../../../web/node_modules/vitest', import.meta.url)),
    '@': fileURLToPath(new URL('../../../../web/', import.meta.url)),
    '@contracts': fileURLToPath(new URL('../../../../packages/', import.meta.url)),
    'react': fileURLToPath(new URL('../../../../web/node_modules/react', import.meta.url)),
    'react-dom': fileURLToPath(new URL('../../../../web/node_modules/react-dom', import.meta.url)),
  } },
  test: { include: ['tests/lanes/L25/M11/*.test.{ts,tsx}'], maxWorkers: 1 },
};
