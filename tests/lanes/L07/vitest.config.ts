import { defineConfig } from '../../../web/node_modules/vitest/dist/config.js';
import { fileURLToPath } from 'node:url';
export default defineConfig({resolve:{alias:{'@beirut-time/i18n':fileURLToPath(new URL('../../../packages/i18n/src/index.ts',import.meta.url))}},test:{include:['tests/lanes/L07/**/*.test.ts'],maxWorkers:1}});
