import { defineConfig } from '../../../../web/node_modules/vitest/dist/config.js';
import { fileURLToPath } from 'node:url';
const web=fileURLToPath(new URL('../../../../web/',import.meta.url));
export default defineConfig({esbuild:{jsx:'automatic'},resolve:{alias:{'@':web,react:web+'node_modules/react','react-dom':web+'node_modules/react-dom'}},test:{include:['tests/lanes/L18/M03/*.test.tsx'],maxWorkers:1}});
