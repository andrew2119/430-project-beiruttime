import { defineConfig } from '../../../../web/node_modules/vitest/dist/config.js';
import { fileURLToPath } from 'node:url';
const local=(path:string)=>fileURLToPath(new URL(path,import.meta.url));
export default defineConfig({esbuild:{jsx:'automatic'},resolve:{alias:{
  '@':local('../../../../web'),
  'vitest':local('../../../../web/node_modules/vitest/dist/index.js'),
  'react':local('../../../../web/node_modules/react'),
  'react-dom/server':local('../../../../web/node_modules/react-dom/server.node.js'),
  '@beirut-time/ui/foundation':local('../../../../packages/ui/src/foundation/index.ts'),
}},test:{include:['tests/lanes/L22/NOTICE/*.test.tsx'],maxWorkers:1}});
