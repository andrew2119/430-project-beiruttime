import { defineConfig, globalIgnores } from 'eslint/config';
import next from 'eslint-config-next/core-web-vitals';
import ts from 'eslint-config-next/typescript';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
// The shared package is part of the same interface and follows the same lint bar.
export default defineConfig([
  ...[...next, ...ts].map(config => ({ ...config, basePath: root })),
  globalIgnores(['**/.next/**', '**/next-env.d.ts', '**/registry.generated.ts']),
  {
    basePath: root,
    settings: { next: { rootDir: `${root}web/` } },
    files: ['web/**/*.{js,jsx,mjs,ts,tsx}', 'packages/ui/src/**/*.{ts,tsx}'],
    rules: { '@next/next/no-img-element': 'error' },
  },
]);
