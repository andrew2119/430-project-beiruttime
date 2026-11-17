import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../../..', import.meta.url));
export default defineConfig({
  esbuild:{jsx:'automatic'},
  resolve:{alias:{'react-dom/server':`${root}/web/node_modules/react-dom/server.node.js`,'react':`${root}/web/node_modules/react`,'@':`${root}/web`,'@beirut-time/ui/foundation':`${root}/packages/ui/src/foundation/index.ts`}},
  test:{include:['tests/lanes/L22/M09/*.test.tsx'],environment:'node',maxWorkers:1},
});
