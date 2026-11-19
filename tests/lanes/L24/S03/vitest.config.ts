import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
import { realpathSync } from 'node:fs';
const root = fileURLToPath(new URL('../../../../web/',import.meta.url));
export default defineConfig({root,esbuild:{jsx:'automatic'},resolve:{alias:{'react':realpathSync(root+'node_modules/react'),'react-dom':realpathSync(root+'node_modules/react-dom'),'@':root,'@contracts':fileURLToPath(new URL('../../../../packages/',import.meta.url))}},test:{include:['../tests/lanes/L24/S03/*.test.tsx'],maxWorkers:1}});
