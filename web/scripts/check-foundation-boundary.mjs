import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const LEGACY_UI_INVENTORY = 'web/tests/legacy-ui-sources.json';
export const CLEANUP_BASE = '1016d21f88e713d21a197d85f65198fb8346d62e';
export const CLEANUP_MAIN = '7a18fdaf45e3ac4d6cb3df85e3b6ca09c3457c0a';
export const CLEANUP_FOUNDATION = '39b157b74bc32d695e5aa159ce9971bd146f4620';
const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const digest = value => createHash('sha256').update(value).digest('hex');
const git = args => execFileSync('git', args, {cwd:ROOT, encoding:'utf8', stdio:['ignore','pipe','pipe']});
let cleanup;
/** One reviewed, immutable main integration. Only an existing source whose
 * accepted bytes exactly match the old main blob can receive its exact new
 * blob. Later edits, copied paths, new files and moving branch tips never match. */
export function cleanupBoundary(file) {
  if (!cleanup) {
    cleanup = new Map();
    const tree = ref => new Map(git(['ls-tree','-r',ref,'--','web','packages/ui/src']).trim().split('\n').filter(Boolean).map(line => {
      const [,blob,path] = /^\d+ blob ([\da-f]+)\t(.+)$/.exec(line);
      return [path,blob];
    }));
    const base = tree(CLEANUP_BASE), accepted = tree(CLEANUP_FOUNDATION), incoming = tree(CLEANUP_MAIN);
    for (const [path,beforeBlob] of base) {
      const afterBlob = incoming.get(path);
      if (!/\.(?:css|[cm]?[jt]sx?)$/.test(path) || beforeBlob !== accepted.get(path) || !afterBlob || beforeBlob === afterBlob) continue;
      cleanup.set(path,Object.freeze({
        beforeBlob,afterBlob,
        before:digest(git(['show',`${CLEANUP_BASE}:${path}`])),
        after:digest(git(['show',`${CLEANUP_MAIN}:${path}`])),
      }));
    }
  }
  return cleanup.get(file);
}
export function cleanupBoundaryHash(file, hash) {
  const pair = cleanupBoundary(file);
  return pair?.before === hash ? pair.after : hash;
}
export function isCleanupBlob(file, blob, headBlob) {
  const pair = cleanupBoundary(file);
  return !!pair && pair.beforeBlob === headBlob && pair.afterBlob === blob;
}
export function cleanupLedgerHashes(ledger) {
  return Object.fromEntries(Object.entries(ledger).map(([file,entry]) => [file,{...entry,sha256:cleanupBoundaryHash(file,entry.sha256)}]));
}

/** Legacy component/style bytes are not a second editable primitive family.
 * Deleting a final implementation also removes its exports and consumers;
 * type checks and the per-component retirement review prove that removal. */
export function legacyUiIssues(root) {
  const inventory = JSON.parse(readFileSync(join(root, LEGACY_UI_INVENTORY), 'utf8'));
  const accepted = JSON.parse(git(['show',`HEAD:${LEGACY_UI_INVENTORY}`]));
  const failures = [];
  for (const [file, hash] of Object.entries(inventory)) {
    if (!accepted[file] || cleanupBoundaryHash(file,accepted[file]) !== hash) failures.push(`${file}: bt-control-detour frozen inventory cannot grow or be rehashed`);
    if (!existsSync(join(root, file))) continue;
    if (digest(readFileSync(join(root, file))) !== hash) failures.push(`${file}: bt-control-detour frozen compatibility implementation/style cannot change`);
  }
  return failures;
}
