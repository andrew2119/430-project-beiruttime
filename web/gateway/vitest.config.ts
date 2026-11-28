import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
import base from '../vitest.config';

export default defineConfig({
  ...base,
  root: fileURLToPath(new URL('../', import.meta.url)),
  test: { ...base.test, include: ['gateway/**/*.test.ts', 'tests/gateway-*.test.ts'] },
});
