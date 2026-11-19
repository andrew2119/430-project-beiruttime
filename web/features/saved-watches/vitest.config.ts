import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
const web = fileURLToPath(new URL('../..',import.meta.url));
export default defineConfig({
  esbuild:{jsx:'automatic'},
  resolve:{alias:{'@':web,'react':`${web}/node_modules/react`,'react-dom':`${web}/node_modules/react-dom`,'vitest':`${web}/node_modules/vitest/dist/index.js`}},
  test:{include:['../tests/lanes/L22/M02/*.test.tsx'],maxWorkers:1},
});
