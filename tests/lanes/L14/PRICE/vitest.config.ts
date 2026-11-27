import { defineConfig } from '../../../../web/node_modules/vitest/dist/config.js';
import { fileURLToPath } from 'node:url';
export default defineConfig({esbuild:{jsx:'automatic'},resolve:{alias:{'react':fileURLToPath(new URL('../../../../web/node_modules/react',import.meta.url)),'@tanstack/react-query':fileURLToPath(new URL('../../../../web/node_modules/@tanstack/react-query',import.meta.url)),'@':fileURLToPath(new URL('../../../../web',import.meta.url))}},test:{include:['tests/lanes/L14/PRICE/*.test.ts'],maxWorkers:1}});
