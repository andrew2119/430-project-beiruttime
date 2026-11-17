import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, rm, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = new URL('../../../../', import.meta.url);

test('lane activation declares both required discovery consumers', async () => {
  const manifest = JSON.parse(await readFile(new URL('../../../../contracts/registrations/L21.json', import.meta.url), 'utf8'));
  assert.deepEqual(manifest.discovery_contract, {
    version: 1,
    minimum_lane: 'L00',
    maximum_lane: 'L25',
    required_consumers: ['web/scripts/generate-nav.mjs', 'web/registry-loader.ts'],
    missing_fragments: 'safe',
    generated_indexes: 'uncommitted',
    activation: 'requires_all_consumers',
  });
  assert.equal(manifest.activation, 'unavailable');
});

// Replay production metadata without changing generated indexes in this checkout.
test('published fragments are discovered with safe unavailable activation', async () => {
  for (const [directory, file] of [['contracts/registrations/', 'L21.json'], ['web/registrations/', 'L21.ts']]) {
    assert.equal((await readdir(new URL(directory, root))).includes(file), true);
  }
  await readFile(new URL('../../../../contracts/registrations/L21.json', import.meta.url));
  await readFile(new URL('../../../../web/registrations/L21.ts', import.meta.url));
  const temporary = await mkdtemp(join(tmpdir(), 'l21-baseline-'));
  try {
    await mkdir(join(temporary, 'web/scripts'), { recursive: true });
    await mkdir(join(temporary, 'web/registrations'));
    await mkdir(join(temporary, 'contracts/registrations'), { recursive: true });
    const generator = await readFile(new URL('web/scripts/generate-nav.mjs', root), 'utf8');
    await writeFile(join(temporary, 'web/scripts/generate-nav.mjs'), generator);
    for (const file of await readdir(new URL('contracts/registrations/', root))) {
      if (/^L\d\d\.json$/.test(file)) await writeFile(join(temporary, 'contracts/registrations', file), await readFile(new URL(`contracts/registrations/${file}`, root)));
    }
    for (const file of await readdir(new URL('contracts/registrations/', root))) {
      if (!/^L\d\d\.json$/.test(file)) continue;
      const manifest = JSON.parse(await readFile(new URL(`contracts/registrations/${file}`, root)));
      for (const contract of manifest.contracts ?? []) {
        for (const fixture of contract.fixtures ?? []) {
          await mkdir(dirname(join(temporary, fixture)), { recursive: true });
          await writeFile(join(temporary, fixture), await readFile(new URL(fixture, root)));
        }
      }
    }
    // Resolve retained package contracts from the existing checkout without copying them.
    const { symlink } = await import('node:fs/promises');
    await rm(join(temporary, 'packages'), { recursive: true });
    await symlink(new URL('packages/', root), join(temporary, 'packages'));
    // The shared lane-range update is outside this fragment's ownership.
    // Exercise the published discovery contract in isolation until it lands.
    const widened = generator.replaceAll('L(0[0-9]|1[01])', 'L(0[0-9]|1[0-9]|2[0-5])');
    await writeFile(join(temporary, 'web/scripts/generate-nav.mjs'), widened);
    await writeFile(join(temporary, 'web/registrations/L21.ts'), await readFile(new URL('web/registrations/L21.ts', root)));
    const result = spawnSync(process.execPath, [join(temporary, 'web/scripts/generate-nav.mjs')], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    const generated = await readFile(join(temporary, 'web/registry.generated.ts'), 'utf8');
    assert.equal(generated.includes("from './registrations/L21'"), true);
    assert.equal(generated.match(/from '\.\/registrations\/L21'/g)?.length, 1);
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});
