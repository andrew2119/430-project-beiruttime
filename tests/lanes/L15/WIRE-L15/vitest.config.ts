import { defineConfig } from '../../../../web/node_modules/vitest/dist/config.js';
export default defineConfig({test:{include:['tests/lanes/L15/WIRE-L15/*.test.ts'],maxWorkers:1}});
