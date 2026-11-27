import {defineConfig} from 'vitest/config';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
export default defineConfig({
 resolve:{alias:[{find:/^@tanstack\/react-query$/,replacement:createRequire(import.meta.url).resolve('@tanstack/react-query')},{find:'@',replacement:fileURLToPath(new URL('../../',import.meta.url))},{find:/^react$/,replacement:createRequire(import.meta.url).resolve('react')}]},
 esbuild:{jsx:'automatic'},
 test:{include:['../tests/lanes/L13/O09/*.test.tsx'],maxWorkers:1},
});
