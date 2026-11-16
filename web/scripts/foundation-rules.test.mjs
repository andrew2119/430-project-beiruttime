import assert from 'node:assert/strict';
import { test } from 'node:test';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { execFileSync } from 'node:child_process';
import ts from 'typescript';
import { ROOT, LEDGER, census, cssDeclarations, declaredLayers, hashSource, inspectSource, measureReference } from './check-ui-rules.mjs';
import { LEGACY_UI_INVENTORY, legacyUiIssues } from './check-foundation-boundary.mjs';
import { FOUNDATION_ENTRY } from './foundation-boundary.mjs';
import { splitOutside } from './token-cascade.mjs';
import { surfacePointer, surfacePadding } from '../tests/helpers/component-cascade.mjs';

const layers = declaredLayers(readFileSync(join(ROOT,'web/styles/tokens.css'),'utf8'));
const git = (...args) => execFileSync('git', args, {cwd:ROOT, encoding:'utf8'});
test('one exact canonical entry extends exports without any dependency or version change', () => {
  const manifest = JSON.parse(readFileSync(join(ROOT, 'packages/ui/package.json'), 'utf8'));
  const original = JSON.parse(git('show', 'main:packages/ui/package.json'));
  assert.deepEqual(manifest, {...original, exports:{...original.exports, './motion':'./src/motion-tokens.ts', './motion-easing':'./src/motion-easing.ts', './foundation':'./src/foundation/index.ts'}});
  assert.deepEqual(inspectSource('web/features/review/control.tsx', `import {Button} from '${FOUNDATION_ENTRY}'; export default()=> <Button>Review</Button>;`), {});
  assert.ok(inspectSource('web/features/review/control.tsx', "import {Button} from '@beirut-time/ui/foundation/button';")['bt-control-detour']);
});

test('only exact HEAD consumers retain root controls; edits and copied paths use canonical controls', () => {
  const directory = mkdtempSync(join(ROOT, '.bt-foundation-probe-'));
  const write = (file, source) => {mkdirSync(dirname(join(directory,file)), {recursive:true}); writeFileSync(join(directory,file), source);};
  try {
    const file = 'web/shell/toaster.tsx', source = git('show', `HEAD:${file}`);
    write(file, source);
    assert.equal(census(directory)[file].counts['bt-control-detour'] ?? 0, 0);
    write(file, source + '\n/* changed */');
    assert.ok(census(directory)[file].counts['bt-control-detour']);
    write('web/features/review/toaster.tsx', source);
    assert.ok(census(directory)['web/features/review/toaster.tsx'].counts['bt-control-detour']);
    write(file, source.replace("'@beirut-time/ui'", "'@beirut-time/ui/foundation'"));
    assert.equal(census(directory)[file].counts['bt-control-detour'] ?? 0, 0);
  } finally {rmSync(directory, {recursive:true, force:true});}
});

test('legacy components and styles stay at their original bytes with only the preceding lint comment boundary', () => {
  const inventory = JSON.parse(readFileSync(join(ROOT, LEGACY_UI_INVENTORY), 'utf8'));
  const paths = git('ls-tree', '-r', '--name-only', 'main', '--', 'packages/ui/src', 'web/styles', 'web/shell/primitives.tsx').trim().split('\n').filter(file => !['packages/ui/src/motion-tokens.ts','web/styles/tokens.css'].includes(file));
  assert.deepEqual(Object.keys(inventory), paths);
  for (const file of paths) {
    if (file === 'packages/ui/src/image-frame.tsx') {
      assert.equal(inventory[file], '436fa430e6b56883220208de2a0eee1476588f08859eda84aa12e378d5d8d40d');
      const compile = source => ts.transpileModule(source, {compilerOptions:{target:ts.ScriptTarget.ES2022, module:ts.ModuleKind.ESNext, jsx:ts.JsxEmit.ReactJSX, removeComments:true}}).outputText;
      assert.equal(compile(readFileSync(join(ROOT,file),'utf8')), compile(git('show', `main:${file}`)));
    } else assert.equal(inventory[file], hashSource(git('show', `main:${file}`)), file);
  }
  assert.deepEqual(legacyUiIssues(ROOT), []);
  const directory = mkdtempSync(join(ROOT, '.bt-foundation-probe-'));
  try {
    mkdirSync(join(directory,'web/tests'), {recursive:true});
    writeFileSync(join(directory,LEGACY_UI_INVENTORY), JSON.stringify({'packages/ui/src/button.tsx':inventory['packages/ui/src/button.tsx']}));
    mkdirSync(join(directory,'packages/ui/src'), {recursive:true});
    const file = join(directory,'packages/ui/src/button.tsx');
    writeFileSync(file, git('show','main:packages/ui/src/button.tsx'));
    assert.deepEqual(legacyUiIssues(directory), []);
    writeFileSync(file, readFileSync(file,'utf8') + '\n/* changed */');
    assert.ok(legacyUiIssues(directory).some(line => line.includes('frozen compatibility')));
  } finally {rmSync(directory,{recursive:true,force:true});}
});

test('canonical State announces errors without pretending the unchanged legacy gap is repaired', async () => {
  const canonical = 'packages/ui/src/foundation/state.tsx';
  assert.ok(existsSync(join(ROOT,canonical)));
  assert.deepEqual(inspectSource(canonical, readFileSync(join(ROOT,canonical),'utf8')), {});
  assert.equal(inspectSource('packages/ui/src/index.tsx', git('show','main:packages/ui/src/index.tsx'), {legacyMotionAllowed:true})['bt-state-alert-gap'], 1);
  const ledger = JSON.parse(readFileSync(join(ROOT,LEDGER),'utf8'));
  assert.equal(Object.keys(ledger).length,92);
  assert.equal(Object.values(ledger).flatMap(entry => Object.values(entry.counts)).reduce((a,b)=>a+b,0),324);
  assert.deepEqual(await measureReference(),ledger);
});


test('only the two canonical modal hosts receive viewport coverage permission', () => {
  const file = 'web/styles/bt-components.css';
  for (const host of ['.bt-surface-stage','.bt-surface-shade']) {
    const source = `@layer components { :where(${host}) {position:fixed;inset:0;z-index:var(--bt-layer-window);} }`;
    assert.deepEqual(inspectSource(file,source,{layers}),{});
    assert.ok(inspectSource('web/styles/private-surface.css',source,{layers})['bt-modal-detour']);
    for (const changed of [source.replace(host,host+', .bt-private'),source.replace(host,'.bt-private'),source.replace('@layer components','@layer private'),source.replace(`:where(${host})`,`.wrapper :where(${host})`)]) assert.ok(inspectSource(file,changed,{layers})['bt-modal-detour']);
  }
});

test('canonical component hosts are zero-specificity and only the motion owner defines motion', () => {
  const zeroHost = selector => {
    if (!selector.startsWith(':where(')) return false;
    let depth = 1, at = 7;
    for (;at<selector.length && depth;at++) {if (selector[at] === '(') depth++;if (selector[at] === ')') depth--;}
    return depth === 0 && /^(?:::before|::after)?$/.test(selector.slice(at));
  };
  for (const file of ['web/styles/bt-components.css','web/styles/bt-component-board.css']) {
    const source = readFileSync(join(ROOT,file),'utf8');assert.deepEqual(inspectSource(file,source,{layers}),{});
    const entries = cssDeclarations(source);
    for (const entry of entries.filter(entry=>entry.context.includes('@layer components'))) for (const branch of splitOutside(entry.context.at(-1),/,/)) assert.ok(zeroHost(branch),branch);
    assert.ok(entries.every(entry=>!entry.prop.startsWith('animation') && !entry.prop.startsWith('transition')),file);
  }
});

test('canonical number formatting has one explicit digit owner and no implicit consumers', () => {
  const paths = Object.keys(census()).filter(file=>file.startsWith('packages/ui/src/foundation/') || file.startsWith('web/internal/components/'));
  for (const file of paths.filter(file=>/\.tsx?$/.test(file))) {
    const source = readFileSync(join(ROOT,file),'utf8');
    assert.ok(!/\.toLocale(?:String|DateString|TimeString)\s*\(/.test(source),file);
    if (file !== 'packages/ui/src/foundation/numbers.ts') assert.ok(!/new\s+Intl\.(?:NumberFormat|DateTimeFormat)\s*\(/.test(source),file);
  }
  const source = readFileSync(join(ROOT,'packages/ui/src/foundation/numbers.ts'),'utf8');
  assert.equal((source.match(/new Intl.NumberFormat/g) ?? []).length,1);
  assert.ok(source.includes("{...options,numberingSystem:locale === 'ar' ? 'arab' : 'latn'}"));
});


test('canonical typography outranks real element resets without raising host specificity', () => {
  const preflight = readFileSync(join(ROOT,'web/node_modules/tailwindcss/preflight.css'),'utf8');
  assert.ok(/h1,[\s\S]*?font-size:\s*inherit/.test(preflight));
  const source = readFileSync(join(ROOT,'web/styles/typography.css'),'utf8');
  const entries = cssDeclarations(source);
  assert.ok(entries.filter(entry=>entry.prop === 'font-size' || entry.prop === 'font-weight').every(entry=>entry.context.includes('@layer components')));
  assert.ok(entries.some(entry=>entry.context.at(-1) === ':where(.bt-heading)' && entry.prop === 'font-size' && entry.value === 'var(--bt-text-heading)'));
  assert.ok(entries.every(entry=>entry.context.at(-1).startsWith(':where(')));
});


test('actual imported motion and component sheets leave closed shade/panel nonblocking', () => {
  for (const classes of [['bt-shade','bt-surface-shade'],['bt-window','bt-surface-panel']]) {
    assert.equal(surfacePointer(classes,'open'), 'auto');
    assert.equal(surfacePointer(classes,'closed'), 'none');
  }
});

test('all sheet forms preserve physical horizontal safe insets after responsive shorthand in both directions', () => {
  for (const form of ['bottom','end','responsive','phone']) for (const width of [390,1200]) for (const dir of ['ltr','rtl']) for (const insets of [{left:0,right:0},{left:47,right:9},{left:9,right:47}]) {
    const classes = ['bt-surface-panel',form === 'phone' ? 'bt-window' : `bt-sheet-${form}`];
    const attached = form !== 'phone' || width <= 850;
    const padding = attached ? surfacePadding(classes,form,width,dir,insets) : surfacePadding(['bt-surface-stage'],form,width,dir,insets);
    assert.ok(padding.left >= insets.left,`${form}/${width}/${dir}: left ${padding.left}`);
    assert.ok(padding.right >= insets.right,`${form}/${width}/${dir}: right ${padding.right}`);
    assert.ok(padding.left >= 16 && padding.right >= 16);
  }
});
