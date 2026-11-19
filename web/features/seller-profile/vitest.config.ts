import { defineConfig } from 'vitest/config';
import { realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
export default defineConfig({
 resolve:{alias:{'@tanstack/react-query':realpathSync(fileURLToPath(new URL('../../node_modules/@tanstack/react-query',import.meta.url))),'@':fileURLToPath(new URL('../../',import.meta.url)),react:realpathSync(fileURLToPath(new URL('../../node_modules/react',import.meta.url))),'react-dom':realpathSync(fileURLToPath(new URL('../../node_modules/react-dom',import.meta.url)))}},
 esbuild:{jsx:'automatic'},
 test:{include:['../tests/lanes/L16/L10/*.test.tsx'],maxWorkers:1},
});
