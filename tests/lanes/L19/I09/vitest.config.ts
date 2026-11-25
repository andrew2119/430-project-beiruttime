import { defineConfig } from '../../../../web/node_modules/vitest/dist/config.js';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  resolve: {alias: {
    'next/navigation': fileURLToPath(new URL('../../../../web/node_modules/next/navigation.js', import.meta.url)),
    'vitest': fileURLToPath(new URL('../../../../web/node_modules/vitest/dist/index.js', import.meta.url)),
    '@': fileURLToPath(new URL('../../../../web', import.meta.url)),
    '@contracts': fileURLToPath(new URL('../../../../packages', import.meta.url)),
    'react': fileURLToPath(new URL('../../../../web/node_modules/react', import.meta.url)),
  }},
  test: {include: ['tests/lanes/L19/I09/*.test.ts'], maxWorkers: 1},
});
