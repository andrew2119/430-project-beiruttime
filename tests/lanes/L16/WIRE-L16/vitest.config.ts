import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';
export default defineConfig({
  resolve: { alias: [{ find: './registry.generated', replacement: fileURLToPath(new URL('./empty-index.ts', import.meta.url)) }] },
  test: { include: ['tests/lanes/L16/WIRE-L16/*.test.ts'], maxWorkers: 1 },
});
