import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
const root=fileURLToPath(new URL('../../../../web/',import.meta.url));
export default defineConfig({root,esbuild:{jsx:'automatic'},resolve:{alias:{'next':fileURLToPath(new URL('../../../../web/node_modules/next',import.meta.url)),'react':fileURLToPath(new URL('../../../../web/node_modules/react',import.meta.url)),'@':root,'@contracts':fileURLToPath(new URL('../../../../packages/',import.meta.url))}},test:{include:['../tests/lanes/L22/M06/*.test.ts','../tests/lanes/L22/M06/*.test.tsx'],maxWorkers:1}});
