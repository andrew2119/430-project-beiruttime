import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../../../', import.meta.url));
const config = {
  esbuild:{jsx:'automatic'},
  resolve:{alias:{
    '@':`${root}web`,
    '@contracts':`${root}packages`,
    'react-dom':`${root}web/node_modules/react-dom`,
    'react':`${root}web/node_modules/react`,
    '@beirut-time/ui/foundation':`${root}packages/ui/src/foundation/index.ts`,
  }},
  test:{include:['tests/lanes/L20/P04/*.test.tsx'],maxWorkers:1},
};

export default config;
