import { defineConfig } from '../../../../web/node_modules/vitest/dist/config.js';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  esbuild:{jsx:'automatic'},
  resolve:{alias:{'react-dom/server':fileURLToPath(new URL('../../../../web/node_modules/react-dom/server.js',import.meta.url)),'react/jsx-dev-runtime':fileURLToPath(new URL('../../../../web/node_modules/react/jsx-dev-runtime.js',import.meta.url)),'vitest':fileURLToPath(new URL('../../../../web/node_modules/vitest/dist/index.js',import.meta.url)),'react/jsx-runtime':fileURLToPath(new URL('../../../../web/node_modules/react/jsx-runtime.js',import.meta.url)),'@':fileURLToPath(new URL('../../../../web/',import.meta.url))}},
  test:{include:['tests/lanes/L12/BASE-ADOPT/*.test.tsx'],maxWorkers:1},
});
