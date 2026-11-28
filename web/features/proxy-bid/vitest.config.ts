import {fileURLToPath} from 'node:url';
import {defineConfig} from 'vitest/config';

const webRoot = fileURLToPath(new URL('../..', import.meta.url));

export default defineConfig({
  root: webRoot,
  resolve: {alias: {'@': webRoot}},
  esbuild: {jsx: 'automatic'},
  test: {include: ['features/proxy-bid/**/*.test.{ts,tsx}'], maxWorkers: 1},
});
