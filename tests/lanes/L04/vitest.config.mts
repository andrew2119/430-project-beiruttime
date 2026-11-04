import { fileURLToPath } from 'node:url';
export default {
  root:fileURLToPath(new URL('../../../web',import.meta.url)),
  resolve:{alias:{'@':fileURLToPath(new URL('../../../web',import.meta.url))}},
  test:{include:['features/discovery/**/*.test.ts','features/live-bids/**/*.test.ts'],maxWorkers:2},
};
