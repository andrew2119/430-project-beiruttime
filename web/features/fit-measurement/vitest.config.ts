import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({esbuild:{jsx:'automatic'},resolve:{alias:{'@':fileURLToPath(new URL('../..',import.meta.url))}},test:{include:['features/fit-measurement/*.test.ts','features/fit-measurement/*.test.tsx'],maxWorkers:1}});
