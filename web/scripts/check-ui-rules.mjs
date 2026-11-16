import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { ESLint } from 'eslint';
import { legacyUiIssues } from './check-foundation-boundary.mjs';
import { INTERFACE_CHECKS, SEMANTIC_PLUGIN, SEMANTIC_RULES, TOKEN_OWNER, LEGACY_MOTION_OWNER, declaredLayers, inspectSource } from './ui-source.mjs';
export { INTERFACE_CHECKS, LONG_TIMES, LAYER_SLOTS, MOTION_OWNER, LEGACY_MOTION_OWNER, LEGACY_MOTION_HASH, cssDeclarations, declaredLayers, inspectSource } from './ui-source.mjs';
export { metadataIssues, motionTokenMs } from './ui-syntax.mjs';

export const ROOT = fileURLToPath(new URL('../../', import.meta.url));
export const LEDGER = 'web/tests/ui-rules-baseline.json';
export const hashSource = source => createHash('sha256').update(source).digest('hex');
const production = path => /\.(?:[cm]?[jt]sx?|css)$/.test(path) && !/\.(?:test|spec|d)\.[^.]+$|(?:^|\/)vitest\.config\.|\.generated\./.test(path) && !path.split('/').some(part => ['node_modules', '.next', 'tests', 'scripts', 'public'].includes(part));
export function sourceFiles(root = ROOT) {
  const files = [];
  const walk = folder => {
    if (!existsSync(join(root, folder))) return;
    for (const entry of readdirSync(join(root, folder), { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const path = join(folder, entry.name);
      if (entry.isDirectory()) { if (!['node_modules', '.next', 'tests', 'scripts', 'public'].includes(entry.name)) walk(path); }
      else if (production(path)) files.push(path);
    }
  };
  walk('web'); walk('packages/ui/src'); return files.sort();
}
function linter(root = ROOT) {
  return new ESLint({
    cwd: root,
    overrideConfigFile: join(ROOT, 'web/eslint.config.mjs'),
    ruleFilter: ({ ruleId }) => ruleId.startsWith('jsx-a11y/'),
    overrideConfig: [{
      basePath: root, files: ['**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}'],
      plugins: { 'jsx-a11y': SEMANTIC_PLUGIN },
      languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
      rules: SEMANTIC_RULES,
    }],
  });
}
export function census(root = ROOT) {
  const head = headSources();
  const layers = existsSync(join(root, TOKEN_OWNER)) ? declaredLayers(readFileSync(join(root, TOKEN_OWNER), 'utf8')) : new Set();
  return Object.fromEntries(sourceFiles(root).map(file => {
    const source = readFileSync(join(root, file), 'utf8');
    const blob = createHash(head.algorithm).update(`blob ${Buffer.byteLength(source)}\0`).update(source).digest('hex');
    return [file, { sha256: hashSource(source), counts: inspectSource(file, source, { layers, legacyMotionAllowed:head.files.get(file) === blob }) }];
  }));
}
export async function semanticCensus(root = ROOT) {
  const files = sourceFiles(root).filter(file => /\.[cm]?[jt]sx?$/.test(file));
  if (!files.length) return {};
  const result = {};
  for (const entry of await linter(root).lintFiles(files)) {
    const messages = entry.messages.filter(message => message.ruleId?.startsWith('jsx-a11y/'));
    if (messages.length) result[relative(root, entry.filePath)] = messages.length;
  }
  return result;
}
export async function measure(root = ROOT) {
  const result = census(root);
  for (const [file, count] of Object.entries(await semanticCensus(root))) result[file].counts['jsx-a11y'] = count;
  return result;
}
const git = (root, args) => execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
let cachedHead;
function headSources() {
  const revision = git(ROOT, ['rev-parse', 'HEAD']).trim();
  if (cachedHead?.revision === revision) return cachedHead;
  const files = new Map(git(ROOT, ['ls-tree', '-r', revision, '--', 'web', 'packages/ui/src']).trim().split('\n').filter(Boolean).map(line => {
    const [, hash, file] = /^\d+ blob ([\da-f]+)\t(.+)$/.exec(line);
    return [file, hash];
  }));
  return cachedHead = { revision, files, algorithm:git(ROOT, ['rev-parse', '--show-object-format']).trim() };
}
/** Read source bytes from main itself, not from changed/untracked files. Semantic
 * lint uses the proposed census policy while preserving those exact main bytes. */
export async function measureReference(ref = 'main', root = ROOT) {
  const files = git(root, ['ls-tree', '-r', '--name-only', ref, '--', 'web', 'packages/ui/src']).trim().split('\n').filter(production);
  const tokenSource = git(root, ['show', `${ref}:${TOKEN_OWNER}`]);
  const layers = declaredLayers(tokenSource), result = {}, semantic = linter(root);
  for (const file of files) {
    const source = git(root, ['show', `${ref}:${file}`]);
    // Exact reference bytes describe existing consumers, never a new proposal.
    const counts = inspectSource(file, source, { layers, legacyMotionAllowed:true });
    if (/\.[cm]?[jt]sx?$/.test(file)) {
      const [linted] = await semantic.lintText(source, { filePath: join(root, file) });
      const number = linted.messages.filter(message => message.ruleId?.startsWith('jsx-a11y/')).length;
      if (number) counts['jsx-a11y'] = number;
    }
    if (Object.keys(counts).length) result[file] = { sha256: hashSource(source), counts };
  }
  return result;
}
export function regressions(current, ledger = {}, strict = false) {
  const failures = [];
  for (const [file, { sha256, counts }] of Object.entries(current)) {
    const before = ledger[file], allowed = !strict && before?.sha256 === sha256 ? before.counts : {};
    for (const [check, count] of Object.entries(counts)) {
      if (!(check in INTERFACE_CHECKS)) failures.push(`${file}: unregistered interface check ${check}`);
      if (count > (allowed?.[check] ?? 0)) failures.push(`${file}: ${check} ${count} > ${allowed?.[check] ?? 0}${check === 'bt-style-opaque' ? ' (unreadable indirection requires line-by-line review)' : ''}${before && before.sha256 !== sha256 ? ' (changed file must be clean)' : ''}`);
    }
  }
  for (const [file, entry] of Object.entries(ledger)) for (const [check, count] of Object.entries(entry.counts)) if ((current[file]?.counts[check] ?? 0) < count) failures.push(`${file}: lower the recorded ${check} count to ${current[file]?.counts[check] ?? 0}`);
  return failures;
}
export function ledgerRegressions(candidate, accepted) {
  const failures = [];
  for (const [file, entry] of Object.entries(candidate)) {
    if (!accepted[file] || accepted[file].sha256 !== entry.sha256) failures.push(`${file}: baseline file/hash cannot be added or replaced`);
    if (!entry.counts || !Object.keys(entry.counts).length) failures.push(`${file}: remove an empty baseline entry`);
    for (const [check, count] of Object.entries(entry.counts ?? {})) if (!(check in INTERFACE_CHECKS) || !Number.isSafeInteger(count) || count < 1 || count > (accepted[file]?.counts[check] ?? 0)) failures.push(`${file}: baseline ${check} cannot grow or return`);
  }
  return failures;
}
export function committedHistory(root = ROOT) {
  const initial = git(root, ['log', '--reverse', '--diff-filter=A', '--format=%H', '--', LEDGER]).trim().split('\n')[0];
  if (!initial) return null;
  let accepted = {};
  try { accepted = JSON.parse(git(root, ['show', `HEAD:${LEDGER}`])); } catch { /* A committed deletion is an empty ceiling, never a reset. */ }
  return { initial: JSON.parse(git(root, ['show', `${initial}:${LEDGER}`])), accepted };
}
export function verifyMeasurements(current, ledger, { initial, accepted }, strict = false) {
  return [...regressions(current, ledger, strict), ...ledgerRegressions(ledger, initial), ...ledgerRegressions(ledger, accepted)];
}
/** Check both advertised-check directions and reject any unregistered emitted key.
 * This parser is also used by mutation tests, not just by a snapshot of today's law. */
export function rulebookIssues(law, emitted = []) {
  const rows = [...law.matchAll(/^\| (BT-UI-\d\d) \|(.+)\|$/gm)].map(([, id, rest]) => ({ id, check: rest.split('|').at(-1).trim() }));
  const problems = [], advertised = new Map();
  if (rows.length !== 66 || new Set(rows.map(row => row.id)).size !== 66) problems.push('The rulebook must retain 66 distinct rules.');
  for (const row of rows) {
    const names = [...row.check.matchAll(/\b(?:checks?|gates?)\s+((?:`[\w-]+`|[a-z]+(?:-[\w]+)+)(?:(?:,\s*|\s+and\s+)(?:`[\w-]+`|[a-z]+(?:-[\w]+)+))*)/gi)].flatMap(([, group]) => group.replace(/`/g, '').split(/,\s*|\s+and\s+/));
    advertised.set(row.id, names);
    for (const name of names) if (!(name in INTERFACE_CHECKS)) problems.push(`${row.id}: unregistered advertised check ${name}`);
  }
  for (const [name, id] of Object.entries(INTERFACE_CHECKS)) if (!advertised.get(id)?.includes(name)) problems.push(`${id}: must advertise ${name}`);
  for (const name of emitted) if (!(name in INTERFACE_CHECKS)) problems.push(`Unregistered emitted check ${name}`);
  return problems;
}
export function motionRetirementIssues(root = ROOT) {
  if (existsSync(join(root, LEGACY_MOTION_OWNER))) return [];
  const problems = [];
  for (const file of sourceFiles(root)) {
    const source = readFileSync(join(root, file), 'utf8');
    if (inspectSource(file, source)['bt-motion-legacy']) problems.push(`${file}: bt-motion-legacy remove the last consumer before deleting the frozen sheet`);
  }
  const entry = join(root, 'web/app/globals.css');
  if (existsSync(entry) && /@import\s+["'][^"']*\/motion\.css["']/.test(readFileSync(entry, 'utf8'))) problems.push('web/app/globals.css: bt-motion-legacy remove the retired stylesheet import');
  return problems;
}
export async function run(args = process.argv.slice(2)) {
  if (args.some(arg => !['--report', '--strict'].includes(arg))) throw new Error('Use --report or --strict; the baseline is never regenerated.');
  const current = await measure();
  if (args.includes('--report')) { console.log(JSON.stringify(Object.fromEntries(Object.entries(current).filter(([, entry]) => Object.keys(entry.counts).length)), null, 2)); return 0; }
  const ledger = JSON.parse(readFileSync(join(ROOT, LEDGER), 'utf8'));
  // Before the first commit, main is the only permitted bootstrap source.
  const history = committedHistory() ?? await measureReference().then(initial => ({ initial, accepted: initial }));
  const failures = verifyMeasurements(current, ledger, history, args.includes('--strict'));
  failures.push(...motionRetirementIssues(), ...legacyUiIssues(ROOT));
  failures.push(...rulebookIssues(readFileSync(join(ROOT, 'docs/frontend-rules.md'), 'utf8'), Object.values(current).flatMap(entry => Object.keys(entry.counts))));
  for (const file of ['web/package.json', 'packages/ui/package.json']) {
    const manifest = JSON.parse(readFileSync(join(ROOT, file), 'utf8'));
    for (const name of Object.keys(manifest.dependencies ?? {})) if (/^(?:chart\.js|three|gsap|material-symbols)$/.test(name)) failures.push(`${file}: bt-runtime-weight ${name}`);
  }
  if (failures.length) { console.error(failures.join('\n')); return 1; }
  console.log(`Interface checks passed; ${Object.keys(ledger).length} unchanged Sprint 1 files retain recorded debt. New and changed files are clean.`);
  return 0;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = await run(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
