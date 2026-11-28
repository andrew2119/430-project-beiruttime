import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({resolve:{alias:{'react':fileURLToPath(new URL('../../../../web/node_modules/react',import.meta.url)),'react-dom':fileURLToPath(new URL('../../../../web/node_modules/react-dom',import.meta.url)),'@beirut-time/ui/foundation':fileURLToPath(new URL('../../../../packages/ui/src/foundation/index.ts',import.meta.url)),'@':fileURLToPath(new URL('../../../../web',import.meta.url))}},esbuild:{jsx:'automatic'},test:{include:['tests/lanes/L24/S08/*.test.tsx'],maxWorkers:1}});
