import { execFileSync } from 'node:child_process';
import { readFile, realpath, writeFile } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)),'..');
const inside = (parent,child)=>{const path = relative(parent,child);return !isAbsolute(path) && path !== '..' && !path.startsWith('../');};
const load = async file=>JSON.parse(await readFile(file,'utf8'));
const git = (root,...args)=>execFileSync('git',args,{cwd:root,encoding:'utf8'}).trim();
/** Measures only emitted first-load JavaScript, de-duplicated by real file.
 * Tests use tiny synthetic artifacts, never a production build. */
export async function emittedPageSizes(root) {
  const build = resolve(root,'.next'), realBuild = await realpath(build), stats = await load(resolve(build,'diagnostics/route-bundle-stats.json'));
  if (!Array.isArray(stats) || !stats.length) throw new Error('Missing route bundle diagnostics');
  const pages = {}, chunks = new Map();
  for (const item of stats) {
    if (!item || typeof item.route !== 'string' || !item.route.startsWith('/') || Object.hasOwn(pages,item.route) || !Number.isSafeInteger(item.firstLoadUncompressedJsBytes) || item.firstLoadUncompressedJsBytes < 0 || !Array.isArray(item.firstLoadChunkPaths) || !item.firstLoadChunkPaths.length) throw new Error('Invalid or duplicate route diagnostics');
    const files = new Set();
    for (const name of item.firstLoadChunkPaths) {
      if (typeof name !== 'string' || !name.endsWith('.js')) throw new Error('Invalid JavaScript chunk');
      const file = resolve(root,name);if (!inside(build,file)) throw new Error('Chunk escapes build directory');
      const real = await realpath(file);if (!inside(realBuild,real)) throw new Error('Chunk symlink escapes build directory');files.add(real);
    }
    let bytes = 0;
    for (const file of files) {if (!chunks.has(file)) chunks.set(file,gzipSync(await readFile(file),{level:9}).byteLength);bytes += chunks.get(file);}
    pages[item.route] = bytes;
  }
  return pages;
}
export function parseMeasurement(value) {
  if (!value || value.schema !== 1 || value.unit !== 'gzip-bytes' || !/^[a-f0-9]{40}$/.test(value.commit) || !/^[a-f0-9]{40}$/.test(value.tree) || typeof value.buildId !== 'string' || !value.buildId || !value.pages || typeof value.pages !== 'object' || Array.isArray(value.pages) || !Object.keys(value.pages).length) throw new Error('Invalid build measurement');
  for (const [route,bytes] of Object.entries(value.pages)) if (!route.startsWith('/') || !Number.isSafeInteger(bytes) || bytes < 0) throw new Error('Invalid page size');
  return value;
}
export function comparePageSizes(baseValue,headValue,approval=null) {
  const base = parseMeasurement(baseValue), head = parseMeasurement(headValue), errors = [], rows = [];
  const limits = approval?.pages ?? {};
  if (approval && (approval.baseCommit !== base.commit || approval.headCommit !== head.commit || typeof approval.reason !== 'string' || !approval.reason.trim() || !limits || typeof limits !== 'object' || Array.isArray(limits))) throw new Error('Growth approval must name this exact comparison and reason');
  for (const [route,limit] of Object.entries(limits)) if (!route.startsWith('/') || !Number.isSafeInteger(limit) || limit <= 0 || !Object.hasOwn(head.pages,route)) throw new Error('Invalid growth approval');
  for (const route of [...new Set([...Object.keys(base.pages),...Object.keys(head.pages)])].sort()) {
    const before = base.pages[route], after = head.pages[route];
    if (after === undefined) {rows.push({route,before,after:null,result:'removed'});continue;}
    const growth = after-(before ?? 0), limit = limits[route] ?? 0;
    const passed = (before !== undefined && growth <= 0) || (Object.hasOwn(limits,route) && growth <= limit);
    rows.push({route,before:before ?? null,after,growth,limit,result:passed ? 'within limit' : 'failed'});
    if (!passed) errors.push(`${route}: ${before === undefined ? 'new page' : 'growth'} needs explicit approval (${growth} gzip bytes)`);
  }
  return {passed:!errors.length,rows,errors};
}
/** A measurement is created only by a clean-source build in this same command,
 * never by attaching a current SHA to an old .next directory. */
export async function buildMeasurement(root,authorized) {
  if (!authorized) throw new Error('Production measurement is separate from quick checks; --allow-build is required');
  if (git(root,'status','--porcelain','--untracked-files=all')) throw new Error('Measure a clean committed checkout');
  const commit = git(root,'rev-parse','HEAD'), tree = git(root,'rev-parse','HEAD^{tree}');
  execFileSync('pnpm',['run','build'],{cwd:root,stdio:'inherit'});
  if (git(root,'status','--porcelain','--untracked-files=all') || git(root,'rev-parse','HEAD') !== commit) throw new Error('Source changed during the build');
  const buildId = (await readFile(resolve(root,'.next/BUILD_ID'),'utf8')).trim();
  return parseMeasurement({schema:1,unit:'gzip-bytes',commit,tree,buildId,pages:await emittedPageSizes(root)});
}
export function bindComparisonApproval(value,base,head) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key=>!['baseCommit','reason','pages'].includes(key)) || value.baseCommit !== base) throw new Error('Invalid size approval source');
  // Head provenance comes from the committed file, not a self-referential SHA
  // inside a file that would itself change that SHA.
  return {...value,headCommit:head};
}
/** Only an approval added by this exact change can grant growth. Old files are
 * immutable and cannot be renamed or recycled to widen another comparison. */
export function comparisonApproval(root,base,head) {
  const fields = execFileSync('git',['diff','--name-status','--no-renames','-z',base,head,'--',':(top)web/perf/approvals/'],{cwd:root,encoding:'utf8'}).split('\0').filter(Boolean), added = [];
  for (let index=0;index<fields.length;index+=2) {if (fields[index] !== 'A' || !fields[index+1].endsWith('.json')) throw new Error('Size approvals are append-only JSON additions');added.push(fields[index+1]);}
  if (added.length > 1) throw new Error('Use one bounded approval per change');
  return added.length ? bindComparisonApproval(JSON.parse(git(root,'show',`${head}:${added[0]}`)),base,head) : null;
}
async function main(args) {
  const [command,...rest] = args, options = new Map();
  for (let index=0;index<rest.length;index++) {const key = rest[index];if (key === '--allow-build') options.set(key,true);else {if (!['--out','--base','--head','--root'].includes(key) || !rest[index+1]) throw new Error('Unknown size argument');options.set(key,rest[++index]);}}
  const root = resolve(options.get('--root') ?? ROOT);
  if (command === 'measure') {if (!options.get('--out')) throw new Error('--out is required');const result = await buildMeasurement(root,options.get('--allow-build') === true);await writeFile(resolve(options.get('--out')),JSON.stringify(result,null,2)+'\n');return;}
  if (command !== 'compare' || !options.get('--base') || !options.get('--head')) throw new Error('Use measure --out or compare --base --head');
  const base = parseMeasurement(await load(options.get('--base'))), head = parseMeasurement(await load(options.get('--head')));
  for (const source of [base,head]) if (git(root,'rev-parse',`${source.commit}^{tree}`) !== source.tree) throw new Error('Measurement source tree does not match its commit');
  const report = comparePageSizes(base,head,comparisonApproval(root,base.commit,head.commit));
  console.log(JSON.stringify(report,null,2));if (!report.passed) process.exitCode = 1;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2)).catch(error=>{console.error(error.message);process.exitCode = 1;});
