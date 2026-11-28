import { defineConfig } from '../../../../web/node_modules/vitest/dist/config.js';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  esbuild: {jsx: 'automatic'},
  resolve: {alias: {
    'react-dom/server': fileURLToPath(new URL('../../../../web/node_modules/react-dom/server.js', import.meta.url)),
    'react': fileURLToPath(new URL('../../../../web/node_modules/react', import.meta.url)),
    'next/navigation': fileURLToPath(new URL('../../../../web/node_modules/next/navigation.js', import.meta.url)),
    '@contracts': fileURLToPath(new URL('../../../../packages', import.meta.url)),
    '@': fileURLToPath(new URL('../../../../web', import.meta.url)),
    '@beirut-time/ui/foundation': fileURLToPath(new URL('../../../../packages/ui/src/foundation/index.ts', import.meta.url)),
  }},
  test: {include: ['tests/lanes/L22/O04/**/*.test.ts*'], maxWorkers: 1},
});
