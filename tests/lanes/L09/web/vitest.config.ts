import { fileURLToPath } from 'node:url';
const web=fileURLToPath(new URL('../../../../web/',import.meta.url));
export default {root:web,resolve:{alias:{'@':web}},test:{include:['../tests/lanes/L09/web/*.test.ts'],maxWorkers:1}};
