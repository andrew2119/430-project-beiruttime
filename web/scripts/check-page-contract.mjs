import { existsSync, readFileSync, readdirSync, realpathSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)),'../..');
export const PAGE_TABLE = 'web/lib/page-speed/pages.json';
export const MIGRATION = 'web/tests/page-migration.json';
const hash = value=>createHash('sha256').update(value).digest('hex');
const json = (root,file)=>JSON.parse(readFileSync(join(root,file),'utf8'));
function pagesIn(root,path='web/app') {return readdirSync(join(root,path),{withFileTypes:true}).flatMap(entry=>entry.isDirectory() ? pagesIn(root,`${path}/${entry.name}`) : /^page\.[jt]sx?$/.test(entry.name) ? [`${path}/${entry.name}`] : []);}
export function routeOf(file) {return '/'+file.replace(/^web\/app\//,'').replace(/\/page\.[jt]sx?$/,'').split('/').filter(part=>!part.startsWith('(')).join('/');}
const optionalGit = (root,ref,file)=>{try {return execFileSync('git',['show',`${ref}:${file}`],{cwd:root,encoding:'utf8',stdio:['ignore','pipe','ignore']});} catch {return null;}};
export function validatePageTable(table) {
  const errors = [], files = new Set(), routes = new Set();
  if (!Array.isArray(table) || !table.length) return ['Page table is empty'];
  for (const page of table) {
    if (!page || typeof page !== 'object' || Array.isArray(page)) {errors.push('Invalid page entry');continue;}
    if (Object.keys(page).some(key=>!['route','file','view','kind','reason','content','read','proof'].includes(key))) errors.push('Unknown page-contract field');
    if (typeof page.file !== 'string' || !/^web\/app\/internal\/(?:[a-z0-9-]+\/)*page\.tsx$/.test(page.file) || typeof page.route !== 'string' || page.route !== routeOf(page.file)) errors.push('Page must name its exact internal route/file');
    if (files.has(page.file) || routes.has(page.route)) errors.push(`Duplicate page ${page.route}`);files.add(page.file);routes.add(page.route);
    if (!['static','reads'].includes(page.kind) || (page.kind === 'static' ? page.read !== 'none' : page.read !== 'page-demo')) errors.push(`${page.route}: unreviewed read policy`);
    if (typeof page.reason !== 'string' || !page.reason.trim() || typeof page.content !== 'string' || !page.content.trim() || page.proof !== 'owed') errors.push(`${page.route}: missing reason/content or unmeasured verdict`);
    if (!page.view && page.file !== 'web/app/internal/components/page.tsx') errors.push(`${page.route}: shared page view is required`);
    if (page.view && (typeof page.view !== 'string' || !/^web\/internal\/[a-z0-9-]+\/view\.tsx$/.test(page.view))) errors.push(`${page.route}: invalid view source`);
  }
  return errors;
}
/** New reads belong to the shared definition/cache; unchanged older consumers
 * remain migration debt, never an invitation for another direct query family. */
function privateReadImport(file,specifier) {
  const target = specifier.startsWith('@/') ? resolve('/web',specifier.slice(2)) : specifier.startsWith('.') ? resolve(dirname('/'+file),specifier) : '';
  if (!target.startsWith('/web/lib/page-speed/')) return false;
  const name = target.slice('/web/lib/page-speed/'.length).replace(/\.[jt]sx?$/,'').replace(/\/index$/,'');
  if (['definition','read','arrival','address'].includes(name)) return false;
  const owners = {
    scope:['web/lib/page-speed/memory.ts','web/lib/page-speed/provider.tsx','web/lib/page-speed/definition.ts','web/lib/page-speed/engine.ts','web/lib/page-speed/pages.ts','web/lib/page-speed/read.ts'],
    memory:['web/lib/page-speed/provider.tsx','web/shell/shell-boundary.tsx'],
    provider:['web/lib/page-speed/read.ts','web/lib/page-speed/arrival.tsx','web/lib/page-speed/mount.tsx','web/shell/foundation/shell.tsx'],
    engine:['web/lib/page-speed/mount.tsx'],mount:['web/lib/page-speed/loader.tsx'],running:['web/lib/page-speed/mount.tsx','web/shell/foundation/destination.tsx'],
    delay:['web/shell/foundation/destination.tsx'],pages:['web/lib/page-speed/engine.ts','web/shell/foundation/destination.tsx'],'pages.json':['web/lib/page-speed/pages.ts'],loader:['web/shell/foundation/shell.tsx'],
    policy:['web/lib/page-speed/scope.ts','web/lib/page-speed/definition.ts','web/lib/page-speed/read.ts','web/lib/page-speed/engine.ts'],
  };
  return !owners[name]?.includes(file);
}
export function directReadIssues(file,source) {
  const importOwners = ['web/lib/page-speed/scope.ts','web/lib/page-speed/provider.tsx','web/lib/page-speed/definition.ts','web/lib/page-speed/read.ts'];
  const queryOwners = ['web/lib/page-speed/definition.ts','web/lib/page-speed/read.ts'];
  const tree = ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true), errors = [];
  const specifier = value=>{if (/^@tanstack\/react-query(?:\/|$)/.test(value) && !importOwners.includes(file)) errors.push(`${file}: use shared page reads instead of a direct query import`);if (privateReadImport(file,value)) errors.push(`${file}: private page cache/warming parts have one integration owner`);};
  const walk = node=>{
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteralLike(node.moduleSpecifier)) specifier(node.moduleSpecifier.text);
    if (ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || node.expression.getText(tree) === 'require')) {
      if (node.arguments[0] && ts.isStringLiteralLike(node.arguments[0])) specifier(node.arguments[0].text);else errors.push(`${file}: module paths must be explicit for read-owner review`);
    }
    if (ts.isCallExpression(node)) {
      const method = ts.isPropertyAccessExpression(node.expression) ? node.expression.name.text : ts.isElementAccessExpression(node.expression) && ts.isStringLiteralLike(node.expression.argumentExpression) ? node.expression.argumentExpression.text : '';
      if (method === 'prefetch' && file !== 'web/lib/page-speed/engine.ts') errors.push(`${file}: page warming has one shared owner`);
      if (['prefetchQuery','prefetchInfiniteQuery','fetchQuery','fetchInfiniteQuery','ensureQueryData','ensureInfiniteQueryData','refetchQueries'].includes(method) && !queryOwners.includes(file)) errors.push(`${file}: query reads have one shared owner`);
    }
    ts.forEachChild(node,walk);
  };walk(tree);return errors;
}
export function pageContractIssues(root=ROOT) {
  const table = json(root,PAGE_TABLE), migration = json(root,MIGRATION), errors = validatePageTable(table);
  if (errors.length) return errors;
  const readOwned = file=>{try {const actual = realpathSync(join(root,file)), path = relative(realpathSync(root),actual);if (path === '..' || path.startsWith('../') || isAbsolute(path)) throw new Error('outside');return readFileSync(actual,'utf8');} catch {errors.push(`${file}: source is missing or outside this checkout`);return null;}};
  if (!migration.reason?.trim() || !Array.isArray(migration.pages)) return [...errors,'Migration debt needs its reason and exact pages'];
  const acceptedText = optionalGit(root,'HEAD',MIGRATION), accepted = acceptedText ? JSON.parse(acceptedText) : null;
  const frozen = new Map(migration.pages.map(page=>[page.file,page]));
  if (frozen.size !== migration.pages.length) errors.push('Duplicate migration entry');
  for (const page of migration.pages) {
    if (typeof page.file !== 'string' || !/^web\/app\/(?:[\w()[\]-]+\/)*page\.tsx$/.test(page.file) || page.route !== routeOf(page.file) || page.route.startsWith('/internal')) {errors.push(`${page.file}: invalid migration route`);continue;}
    const before = accepted?.pages.find(prior=>prior.file === page.file);
    if (accepted && (!before || JSON.stringify(before) !== JSON.stringify(page))) errors.push(`${page.file}: frozen page ledger cannot grow or be rehashed`);
    const main = accepted ? null : optionalGit(root,'main',page.file);
    if (!accepted && (main == null || hash(main) !== page.sha256)) errors.push(`${page.file}: migration hash must be original main bytes`);
    const source = readOwned(page.file);if (source == null || hash(source) !== page.sha256) errors.push(`${page.file}: frozen page changed before its rebuild`);
  }
  for (const [file,digest] of Object.entries(migration.shell)) {
    if (!/^web\/shell\/[a-z-]+\.tsx$/.test(file)) {errors.push('Invalid frozen shell path');continue;}
    if (accepted && accepted.shell[file] !== digest) errors.push(`${file}: frozen shell ledger cannot grow or be rehashed`);
    const main = accepted ? null : optionalGit(root,'main',file);
    if (!accepted && (main == null || hash(main) !== digest)) errors.push(`${file}: shell hash must be original main bytes`);
    const source = readOwned(file);if (source == null || hash(source) !== digest) errors.push(`${file}: frozen shell changed`);
  }
  const registered = new Map(table.map(page=>[page.file,page]));
  for (const file of pagesIn(root)) if (!registered.has(file) && !frozen.has(file)) errors.push(`${file}: page has no delivery contract or frozen-debt reason`);
  for (const page of table) {
    if (readOwned(page.file) == null) errors.push(`${page.file}: page contract has no owned page`);
    if (page.view) {
      const source = readOwned(page.view) ?? '';
      if (!source.includes("from '@/shell/foundation/page'") || !source.includes('<PageFrame>') || !source.includes('<PageHeader ')) errors.push(`${page.view}: use the shared page composition`);
      if (page.kind === 'reads' && (!source.includes("from '@/lib/page-speed/read'") || !source.includes('usePageRead('))) errors.push(`${page.view}: mounted reads must share the intent definition`);
    }
  }
  // Read all production script sources, not just page entry files.
  const walkSources = directory=>{for (const entry of readdirSync(join(root,directory),{withFileTypes:true})) {const file = `${directory}/${entry.name}`;if (entry.isSymbolicLink()) {errors.push(`${file}: source symlinks are not supported`);continue;}if (entry.isDirectory()) walkSources(file);else if (/\.[cm]?[jt]sx?$/.test(file) && !/\.(?:test|spec)\./.test(file)) {const source = readFileSync(join(root,file),'utf8');if (optionalGit(root,'HEAD',file) !== source) errors.push(...directReadIssues(file,source));}}};
  for (const directory of ['web/app','web/shell','web/features','web/lib','web/internal','packages/ui/src']) if (existsSync(join(root,directory))) walkSources(directory);
  return errors;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {const errors = pageContractIssues();if (errors.length) {console.error(errors.join('\n'));process.exitCode = 1;} else console.log('Page contracts passed; frozen routes have no delivery verdict.');} catch (error) {console.error(error.message);process.exitCode = 1;}
}
