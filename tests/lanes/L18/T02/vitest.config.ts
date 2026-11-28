import { fileURLToPath } from 'node:url';
const config = {
 root:fileURLToPath(new URL('../../../../web',import.meta.url)),
 esbuild:{jsx:'automatic'},
 resolve:{alias:{'@':fileURLToPath(new URL('../../../../web',import.meta.url))}},
 test:{include:['features/disputes/*.test.ts','features/disputes/*.test.tsx'],maxWorkers:1}
};

export default config;
