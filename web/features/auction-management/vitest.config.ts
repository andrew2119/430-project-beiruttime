import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';
export default defineConfig({root:fileURLToPath(new URL('../..',import.meta.url)),resolve:{alias:{'@/features/identity/session':fileURLToPath(new URL('../tests/lanes/L05/web/session-fixture.ts',new URL('../..',import.meta.url))),'@':fileURLToPath(new URL('../..',import.meta.url))}},esbuild:{jsx:'automatic'},test:{include:['features/auction-management/**/*.test.ts'],maxWorkers:1}});
