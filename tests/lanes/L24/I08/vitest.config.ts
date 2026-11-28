import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  esbuild:{jsx:'automatic'},
  resolve:{alias:{'react':fileURLToPath(new URL('../../../../web/node_modules/react',import.meta.url)),'react-dom':fileURLToPath(new URL('../../../../web/node_modules/react-dom',import.meta.url)),'@':fileURLToPath(new URL('../../../../web',import.meta.url)),'@contracts':fileURLToPath(new URL('../../../../packages',import.meta.url))}},
  test:{include:['tests/lanes/L24/I08/*.test.tsx'],maxWorkers:1},
});
