import { defineConfig } from '../../../../web/node_modules/vitest/dist/config.js';
export default defineConfig({
 esbuild:{jsx:'automatic'},
 resolve:{alias:{'@tanstack/react-query':new URL('../../../../web/node_modules/@tanstack/react-query',import.meta.url).pathname,'@beirut-time/ui':new URL('../../../../packages/ui/src/index.ts',import.meta.url).pathname,'react':new URL('../../../../web/node_modules/react',import.meta.url).pathname,'react-dom':new URL('../../../../web/node_modules/react-dom',import.meta.url).pathname,'@':new URL('../../../../web',import.meta.url).pathname,'@beirut-time/i18n':new URL('../../../../packages/i18n/src/index.ts',import.meta.url).pathname}},
 test:{include:['tests/lanes/L14/S02/*.test.{ts,tsx}'],maxWorkers:1},
});
