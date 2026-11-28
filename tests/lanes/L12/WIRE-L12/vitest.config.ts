import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  root: fileURLToPath(new URL('../../../../', import.meta.url)),
  test: { include: ['tests/lanes/L12/WIRE-L12/*.test.ts'], maxWorkers: 1 },
});
