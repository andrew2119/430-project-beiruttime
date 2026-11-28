import { defineConfig } from '../../../../web/node_modules/vitest/dist/config.js';
import { fileURLToPath } from 'node:url';
export default defineConfig({resolve:{alias:{'@tanstack/react-query':fileURLToPath(new URL('../../../../web/node_modules/@tanstack/react-query',import.meta.url)),'react':fileURLToPath(new URL('../../../../web/node_modules/react',import.meta.url)),'@':fileURLToPath(new URL('../../../../web/',import.meta.url))}},esbuild:{jsx:'automatic'},test:{include:['tests/lanes/L14/C09/*.test.{ts,tsx}'],maxWorkers:1}});
