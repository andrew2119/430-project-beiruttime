import { readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';

// Each feature keeps its own test aliases and fixtures; run all of them locally.
const root = fileURLToPath(new URL('../', import.meta.url));
const vitest = fileURLToPath(new URL('../node_modules/vitest/vitest.mjs', import.meta.url));
for (const feature of readdirSync(join(root, 'features')).sort()) {
  const config = join('features', feature, 'vitest.config.ts');
  if (!existsSync(join(root, config))) continue;
  const result = spawnSync(process.execPath, [vitest, 'run', '--config', config], { cwd: root, stdio: 'inherit' });
  if (result.error) console.error(result.error.message);
  if (result.status !== 0) process.exit(result.status ?? 1);
}
