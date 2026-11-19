export default {
  resolve:{alias:{vitest:new URL('../../../../web/node_modules/vitest/dist/index.js',import.meta.url).pathname}},
  test:{include:['tests/lanes/L20/M10/frontend.test.ts'],maxWorkers:1}
};
