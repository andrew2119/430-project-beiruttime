import { defineConfig } from '../../../../web/node_modules/vitest/dist/config.js';
export default defineConfig({ test: { include: ['tests/lanes/L24/WIRE-L24/*.test.ts'], maxWorkers: 1 } });
