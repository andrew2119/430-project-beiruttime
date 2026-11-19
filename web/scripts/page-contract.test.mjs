import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { inspectSource } from './ui-source.mjs';
import { cleanupBoundaryHash } from './check-foundation-boundary.mjs';
import { committedHistory, cssDeclarations, ledgerRegressions, regressions } from './check-ui-rules.mjs';
import { createStartingPage, startingFiles } from './new-page.mjs';
import { directReadIssues, PAGE_TABLE, pageContractIssues, validatePageTable } from './check-page-contract.mjs';
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)),'../..'), rootFile = 'web/app/layout.tsx';
const root = readFileSync(join(ROOT,rootFile),'utf8');
const hash = source=>createHash('sha256').update(source).digest('hex');
const spec = {slug:'notes',en:'Collector <notes>',ar:'ملاحظات الجامع',bodyEn:'Content',bodyAr:'المحتوى',reason:'No server data.'};
function temporaryCandidate(run) {
  const directory = mkdtempSync(join(tmpdir(),'page-contract-candidate-'));
  try {
    const files = execFileSync('git',['ls-files','--cached','--others','--exclude-standard','-z'],{cwd:ROOT,encoding:'utf8',stdio:['ignore','pipe','ignore']}).split('\0');
    for (const file of new Set(files)) {
      if (!/^(?:web\/(?:app|shell|features|lib|internal)\/|packages\/ui\/src\/)/.test(file) && file !== 'web/tests/page-migration.json') continue;
      if (!existsSync(join(ROOT,file))) continue;
      mkdirSync(dirname(join(directory,file)),{recursive:true});
      copyFileSync(join(ROOT,file),join(directory,file));
    }
    symlinkSync(join(ROOT,'.git'),join(directory,'.git'));
    return run(directory);
  } finally {rmSync(directory,{recursive:true,force:true});}
}
test('owned document font shape passes only for the exact two immutable local bindings',()=>{
  assert.deepEqual(inspectSource(rootFile,root),{});
  const candidates = [
    root.replace('lexendDeca.variable, arabic.variable','arabic.variable, lexendDeca.variable'),
    root.replace(".join(' ')",".join(' text-red-500 ')"),
    root.replace('lexendDeca.variable, arabic.variable',"lexendDeca.variable, arabic.variable, 'text-red-500'"),
    root.replace("weight: '100 900'","weight: '100 800'"),
    root.replace("from 'next/font/local'","from './unowned-font'"),
    root+'\nconst fontAlias = lexendDeca;\n',root+'\nlexendDeca.variable = "text-red-500";\n',
  ];
  for (const source of candidates) assert.ok(inspectSource(rootFile,source)['bt-style-opaque']);
  assert.ok(inspectSource('web/app/internal/other/page.tsx',root)['bt-style-opaque']);
  assert.ok(inspectSource(rootFile,root.replace("[lexendDeca.variable, arabic.variable].join(' ')",'`${lexendDeca.variable} ${arabic.variable}`'))['bt-style-opaque']);
});
test('temporary root mutation fails; a copied new file receives no font allowance',()=>{
  const directory = mkdtempSync(join(tmpdir(),'font-probe-')), actual = join(directory,'layout.tsx'), copied = join(directory,'page.tsx');
  try {
    writeFileSync(copied,root);assert.ok(inspectSource('web/app/internal/other/page.tsx',readFileSync(copied,'utf8'))['bt-style-opaque']);
    writeFileSync(actual,root.replace('lexendDeca.variable, arabic.variable','lexendDeca.variable, lexendDeca.variable'));
    assert.ok(inspectSource(rootFile,readFileSync(actual,'utf8'))['bt-style-opaque']);
  } finally {rmSync(directory,{recursive:true,force:true});}
});
test('only fixed root debt retires; provenance and every surviving hash/count remain exact',()=>{
  const ledger = JSON.parse(readFileSync(join(ROOT,'web/tests/ui-rules-baseline.json'),'utf8')), {initial} = committedHistory(ROOT);
  assert.equal(Object.keys(initial).length,92);assert.equal(Object.values(initial).reduce((n,entry)=>n+Object.values(entry.counts).reduce((a,b)=>a+b,0),0),324);
  assert.equal(Object.keys(ledger).length,87);assert.equal(Object.values(ledger).reduce((n,entry)=>n+Object.values(entry.counts).reduce((a,b)=>a+b,0),0),317);
  assert.equal(ledger[rootFile],undefined);for (const [file,value] of Object.entries(ledger)) assert.deepEqual(value,{...initial[file],sha256:cleanupBoundaryHash(file,initial[file].sha256)});
  const source = root.replace('<body>','<body className="text-red-500">'), counts = inspectSource(rootFile,source);
  assert.ok(regressions({...ledger,[rootFile]:{sha256:hash(source),counts}},ledger).some(line=>line.includes('bt-palette-inline')));
  assert.ok(ledgerRegressions({...ledger,[rootFile]:initial[rootFile]},ledger).length);
});
test('the exact shell cleanup does not allow a later edit or a forged migration digest',()=>temporaryCandidate(candidate=>{
  const manifest = join(candidate,'web/tests/page-migration.json'), sourcePath = 'web/shell/page-header.tsx', file = join(candidate,sourcePath);
  const original = readFileSync(file,'utf8'), saved = readFileSync(manifest,'utf8');
  assert.deepEqual(pageContractIssues(candidate),[]);
  try {
    const changed = original+'\n/* later edit */';writeFileSync(file,changed);
    assert.ok(pageContractIssues(candidate).some(line=>line.includes(sourcePath) && line.includes('frozen shell changed')));
    const migration = JSON.parse(saved);migration.shell[sourcePath] = hash(changed);writeFileSync(manifest,JSON.stringify(migration));
    assert.ok(pageContractIssues(candidate).some(line=>line.includes(sourcePath) && line.includes('cannot grow or be rehashed')));
  } finally {writeFileSync(file,original);writeFileSync(manifest,saved);}
  assert.equal(readFileSync(file,'utf8'),original);assert.equal(readFileSync(manifest,'utf8'),saved);
  assert.deepEqual(pageContractIssues(candidate),[]);
}));

test('root defaults keep the same words but retire the two invalid title endings',()=>{
  assert.ok(root.includes("'للوقت حُسن الاختيار · بيروت تايم':'Time well chosen · Beirut Time'"));
  assert.ok(inspectSource(rootFile,root.replace('Time well chosen · Beirut Time','Beirut Time — Time well chosen'))['bt-title-format']);
});
test('page table rejects missing policy, duplicates, external routes and invented proof verdicts',()=>{
  const {entry} = startingFiles(spec);assert.deepEqual(validatePageTable([entry]),[]);
  for (const change of [{kind:'own'},{read:'mutation'},{warm:false},{proof:'passed'},{reason:''},{content:''},{route:'/checkout'},{file:'web/app/internal/../checkout/page.tsx'}]) assert.ok(validatePageTable([{...entry,...change}]).length);
  assert.ok(validatePageTable([entry,entry]).length);
  assert.ok(directReadIssues('web/internal/new/view.tsx',"import {useQuery as read} from '@tanstack/react-query';").length);
  assert.ok(directReadIssues('web/internal/new/view.tsx','router.prefetch("/internal/page");').length);
  assert.deepEqual(directReadIssues('web/lib/page-speed/read.ts',"import {useQuery} from '@tanstack/react-query';"),[]);
  for (const [file,source] of [['web/lib/page-speed/private.ts',"import {useQuery} from '@tanstack/react-query';"],['web/internal/new/view.tsx',"import {createReadScope} from '@/lib/page-speed/scope';"],['web/internal/new.tsx',"export {usePageReadScope} from '../lib/page-speed/provider/index.tsx';"],['web/internal/new.tsx',"const load = () => import('@/lib/page-speed/memory');"],['web/internal/new.tsx',"require('@tanstack/react-query');"],['web/internal/new.tsx','client["fetchQuery"]({});'],['web/internal/new.tsx',"const target='@/lib/page-speed/provider'; import(target);"]]) assert.ok(directReadIssues(file,source).length,source);
});
test('generator writes the shared composition, bilingual title, contract and real focused test; never replaces a page',()=>{
  const directory = mkdtempSync(join(tmpdir(),'page-probe-')), outside = mkdtempSync(join(tmpdir(),'page-outside-probe-'));
  try {mkdirSync(dirname(join(directory,PAGE_TABLE)),{recursive:true});writeFileSync(join(directory,PAGE_TABLE),'[]');const entry = createStartingPage(directory,spec);
    assert.equal(entry.route,'/internal/notes');assert.ok(existsSync(join(directory,'web/tests/pages/notes.test.tsx')));
    assert.ok(readFileSync(join(directory,entry.view),'utf8').includes('<PageFrame>'));assert.ok(readFileSync(join(directory,entry.file),'utf8').includes('Collector <notes> · Beirut Time'));
    assert.deepEqual(inspectSource(entry.file,readFileSync(join(directory,entry.file),'utf8')),{});assert.deepEqual(inspectSource(entry.view,readFileSync(join(directory,entry.view),'utf8')),{});
    const table = readFileSync(join(directory,PAGE_TABLE),'utf8');assert.throws(()=>createStartingPage(directory,spec));assert.equal(readFileSync(join(directory,PAGE_TABLE),'utf8'),table);
    assert.throws(()=>startingFiles({...spec,slug:'../escape'}));assert.throws(()=>startingFiles({...spec,reason:''}));
    symlinkSync(outside,join(directory,'web/internal/linked'),'dir');assert.throws(()=>createStartingPage(directory,{...spec,slug:'linked'}),/outside/);assert.equal(existsSync(join(outside,'view.tsx')),false);assert.equal(existsSync(join(directory,'web/app/internal/linked/page.tsx')),false);
  } finally {rmSync(directory,{recursive:true,force:true});rmSync(outside,{recursive:true,force:true});}
});
test('physical new and changed read bypasses and an unregistered JavaScript page are refused, then restored',()=>temporaryCandidate(candidate=>{
  const directory = mkdtempSync(join(candidate,'web/internal/.query-probe-')), file = join(directory,'private.mjs'), pageDirectory = join(candidate,`web/app/internal/query-probe-${process.pid}`), model = join(candidate,'web/internal/components/model.ts'), original = readFileSync(model,'utf8');
  assert.equal(existsSync(pageDirectory),false);
  try {writeFileSync(file,"import {useQuery} from '@tanstack/react-query';");mkdirSync(pageDirectory);writeFileSync(join(pageDirectory,'page.jsx'),'export default function Page(){return null;}');writeFileSync(model,original+"\nimport {createReadScope} from '@/lib/page-speed/scope';\n");
    const errors = pageContractIssues(candidate);assert.ok(errors.some(line=>line.includes('private.mjs') && line.includes('direct query')));assert.ok(errors.some(line=>line.includes('components/model.ts') && line.includes('private page cache')));assert.ok(errors.some(line=>line.includes('page.jsx') && line.includes('no delivery contract')));
  } finally {writeFileSync(model,original);rmSync(directory,{recursive:true,force:true});rmSync(pageDirectory,{recursive:true,force:true});}
  assert.equal(readFileSync(model,'utf8'),original);
}));
test('imported destination recipe retains native vertical scroll and pinch zoom without changing targets or disabled feedback',()=>{
  const globals = readFileSync(join(ROOT,'web/app/globals.css'),'utf8');
  assert.equal((globals.match(/@import ['"]\.\.\/styles\/bt-shell\.css['"]/g) ?? []).length,1);
  const declarations = cssDeclarations(readFileSync(join(ROOT,'web/styles/bt-shell.css'),'utf8'));
  const recipe = Object.fromEntries(declarations.filter(entry=>entry.context.at(-1) === ':where(.bt-destination)').map(entry=>[entry.prop,entry.value]));
  assert.equal(recipe['touch-action'],'pan-y pinch-zoom','Native destination links must not exclude pinch zoom');
  assert.equal(recipe['min-block-size'],'var(--bt-touch-target)');
  assert.equal(recipe['user-select'],'none');
  assert.ok(declarations.some(entry=>entry.context.at(-1) === ':where(.bt-destination[aria-disabled="true"])' && entry.prop === 'transform' && entry.value === 'none'));
  assert.ok(declarations.filter(entry=>entry.prop === 'touch-action').every(entry=>entry.value.split(/\s+/).includes('pinch-zoom')),'No new destination variant may take zoom away');
});
test('all real pages have a contract or exact frozen migration record',()=>{assert.deepEqual(pageContractIssues(ROOT),[]);});

test('public rebuild contracts cannot claim unrelated routes, reads or swapped views',()=>{
  const table=JSON.parse(readFileSync(join(ROOT,'web/shell/foundation/pages.json'),'utf8'));
  assert.deepEqual(validatePageTable(table),[]);
  for (const change of [{view:'web/shell/foundation/about.tsx'},{kind:'reads',read:'page-demo'},{file:'web/app/(browse)/watches/page.tsx',route:'/watches'},{proof:'passed'}]) assert.ok(validatePageTable([{...table[0],...change}]).length);
});

test('compatibility rebuilds must render their declared canonical view, including the single shell boundary',()=>temporaryCandidate(candidate=>{
  for (const file of ['web/shell/profile-block.tsx','web/shell/providers.tsx','web/shell/preferences.tsx','web/shell/route-focus.tsx','web/shell/shell.tsx']) {
    const path=join(candidate,file), original=readFileSync(path,'utf8');
    try {
      writeFileSync(path,original.replace(/return <[^;]+;/,'return null;'));
      assert.ok(pageContractIssues(candidate).some(line=>line.includes(file) && line.includes('shared composition')),file);
    } finally {writeFileSync(path,original);}
  }
  const file=join(candidate,'web/shell/shell-view.tsx'), original=readFileSync(file,'utf8');
  try {
    writeFileSync(file,original.replace(/return <ShellBoundary[\s\S]*?;/,'return null;'));
    assert.ok(pageContractIssues(candidate).some(line=>line.includes('single boundary')));
  } finally {writeFileSync(file,original);}
}));
