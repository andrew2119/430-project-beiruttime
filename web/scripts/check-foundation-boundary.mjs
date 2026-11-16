import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';

export const LEGACY_UI_INVENTORY = 'web/tests/legacy-ui-sources.json';
const digest = value => createHash('sha256').update(value).digest('hex');

/** Legacy component/style bytes are not a second editable primitive family.
 * Deleting a final implementation also removes its exports and consumers;
 * type checks and the per-component retirement review prove that removal. */
export function legacyUiIssues(root) {
  const inventory = JSON.parse(readFileSync(join(root, LEGACY_UI_INVENTORY), 'utf8'));
  const failures = [];
  for (const [file, hash] of Object.entries(inventory)) {
    if (!existsSync(join(root, file))) continue;
    if (digest(readFileSync(join(root, file))) !== hash) failures.push(`${file}: bt-control-detour frozen compatibility implementation/style cannot change`);
  }
  return failures;
}
