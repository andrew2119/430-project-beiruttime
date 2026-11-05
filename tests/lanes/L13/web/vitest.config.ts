import {defineConfig} from 'vitest/config';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
const root=resolve(fileURLToPath(new URL('../../../..',import.meta.url)));
export default defineConfig({esbuild:{jsx:'automatic'},resolve:{alias:[{find:'@tanstack/react-query',replacement:resolve(root,'web/node_modules/@tanstack/react-query')},{find:'react',replacement:resolve(root,'web/node_modules/react')},{find:'react-dom',replacement:resolve(root,'web/node_modules/react-dom')},{find:'@/features/identity/session',replacement:resolve(root,'tests/lanes/L13/web/session-fixture.ts')},{find:'@',replacement:resolve(root,'web')},{find:'@contracts',replacement:resolve(root,'packages')}]},test:{include:['tests/lanes/L13/web/*.test.ts'],maxWorkers:1}});
