import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { createRequire } from 'node:module';

const { ModuleKind, transpile } = createRequire(new URL('../../../../web/package.json', import.meta.url))('typescript');
import registration, { composeL17 } from '../../../../web/registrations/L17';

test('registration imports safely without discovery support', () => {
  expect(registration).toEqual(composeL17());
});

test('registration imports safely when require has no context capability', () => {
  const source = readFileSync(new URL('../../../../web/registrations/L17.ts', import.meta.url), 'utf8');
  const exports = {} as { default: unknown };
  const require = () => { throw new Error('Unexpected module load'); };
  runInNewContext(transpile(source, { module: ModuleKind.CommonJS }), { exports, require });
  expect(exports.default).toEqual(composeL17());
});
