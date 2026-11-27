import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { test } from 'vitest';

test('maintenance submission and intake boundaries', () => {
  execFileSync(process.execPath, [
    '--test',
    '--test-isolation=none',
    fileURLToPath(new URL('../../../tests/lanes/L17/S01/submission.test.mjs', import.meta.url)),
  ], { stdio: 'inherit', timeout: 15_000 });
}, 20_000);
