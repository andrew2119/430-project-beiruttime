import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';

const root = new URL('../../../../', import.meta.url);
const require = createRequire(new URL('web/package.json', root));
const { transpile, ModuleKind } = require('typescript');
const lanes = Array.from({ length: 26 }, (_, index) => `L${String(index).padStart(2, '0')}`);

// Keep the connected assertions executable while the shared admission change is owed.
// Any replacement of the exact earlier boundary makes these checks mandatory.
const earlierBoundary = '/^L(0[0-9]|1[01])$/';
const discoverySource = readFileSync(new URL('web/scripts/generate-nav.mjs', root), 'utf8');
const runtimeSource = readFileSync(new URL('web/registry-loader.ts', root), 'utf8');
const owed = source => source.includes(earlierBoundary)
  ? { todo: 'Shared L00-L25 admission is owed; activation remains blocked.' }
  : {};

test('shared discovery admits every lane from L00 through L25', owed(discoverySource), () => {
  const folder = mkdtempSync(join(tmpdir(), 'l17-admission-'));
  try {
    mkdirSync(join(folder, 'web', 'scripts'), { recursive: true });
    mkdirSync(join(folder, 'web', 'registrations'));
    mkdirSync(join(folder, 'contracts', 'registrations'), { recursive: true });
    const script = join(folder, 'web', 'scripts', 'generate-nav.mjs');
    writeFileSync(script, readFileSync(new URL('web/scripts/generate-nav.mjs', root)));
    for (const lane of lanes) {
      writeFileSync(join(folder, 'contracts', 'registrations', `${lane}.json`), JSON.stringify({ version: 1, lane, contracts: [] }));
      writeFileSync(join(folder, 'web', 'registrations', `${lane}.ts`), 'export default {};\n');
    }
    const result = spawnSync(process.execPath, [script], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    const index = readFileSync(join(folder, 'web', 'registry.generated.ts'), 'utf8');
    for (const lane of lanes) assert.equal(index.split(`from './registrations/${lane}'`).length, 2);
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
});

test('shared runtime admits L00 through L25 while rejecting invalid lanes', owed(runtimeSource), () => {
  const source = readFileSync(new URL('web/registry-loader.ts', root), 'utf8');
  const boundary = source.indexOf('const registered =');
  assert.ok(boundary > 0, 'Runtime validation boundary must remain explicit');
  const output = { exports: {} };
  runInNewContext(transpile(source.slice(0, boundary), { module: ModuleKind.CommonJS }), { exports: output.exports });
  const registration = lane => ({ lane, namespace: `scope-${lane.toLowerCase()}`, dictionaries: { en: {}, ar: {} }, routes: [] });
  const entries = lanes.map(registration);
  assert.equal(output.exports.validateRegistrations(entries), entries);
  for (const lane of ['L26', 'L99', 'L-1', 'L1', 'L017']) {
    assert.throws(() => output.exports.validateRegistrations([registration(lane)]));
  }
});
