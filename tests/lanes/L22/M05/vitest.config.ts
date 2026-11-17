import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({esbuild:{jsx:'automatic'},resolve:{alias:{'react':fileURLToPath(new URL('../../../../web/node_modules/react',import.meta.url)),'next':fileURLToPath(new URL('../../../../web/node_modules/next',import.meta.url)),'@beirut-time/ui/foundation':fileURLToPath(new URL('../../../../packages/ui/src/foundation/index.ts',import.meta.url)),'@':fileURLToPath(new URL('../../../../web',import.meta.url))}},test:{include:['tests/lanes/L22/M05/*.test.tsx'],maxWorkers:1}});
