import { fileURLToPath } from 'node:url';
const at = value=>fileURLToPath(new URL(value,import.meta.url));
const config = {
  esbuild:{jsx:'automatic'},
  resolve:{alias:[
    {find:'@',replacement:at('../../../../web')},
    {find:'@contracts',replacement:at('../../../../packages')},
    {find:'@beirut-time/ui/foundation',replacement:at('../../../../packages/ui/src/foundation/index.ts')},
    {find:'vitest',replacement:at('../../../../web/node_modules/vitest/dist/index.js')},
    {find:'react-dom/server',replacement:at('../../../../web/node_modules/react-dom/server.node.js')},
    {find:'react',replacement:at('../../../../web/node_modules/react')},
  ]},
  test:{include:['tests/lanes/L19/I07/*.test.tsx'],maxWorkers:1},
};
export default config;
