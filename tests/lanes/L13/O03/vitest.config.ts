import {defineConfig} from 'vitest/config';
import base from '../web/vitest.config';
export default defineConfig({...base,test:{...base.test,include:['tests/lanes/L13/O03/*.test.tsx'],maxWorkers:1}});
