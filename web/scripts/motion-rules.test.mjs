import assert from 'node:assert/strict';
import { test } from 'node:test';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { execFileSync } from 'node:child_process';
import ts from 'typescript';
import { ROOT, LEDGER, MOTION_OWNER, LEGACY_MOTION_OWNER, LEGACY_MOTION_HASH, census, cssDeclarations, hashSource, inspectSource, measureReference, motionRetirementIssues, motionTokenMs } from './check-ui-rules.mjs';
import { splitOutside } from './token-cascade.mjs';

const css = readFileSync(join(ROOT,MOTION_OWNER),'utf8');
const entries = cssDeclarations(css);
const roots = Object.fromEntries(entries.filter(entry => entry.context.length === 1 && entry.context[0] === ':root').map(entry => [entry.prop,entry.value]));

test('one new owner holds all finite pacing and exact shared curves', () => {
  const long=new Set(['--bt-motion-theme','--bt-motion-icon','--bt-motion-pulse','--bt-motion-safety']);
  for (const [name,value] of Object.entries(roots)) if (name.startsWith('--bt-motion-')) {
    const ms=motionTokenMs(value,roots);
    assert.notEqual(ms,null,name);assert.ok(ms>=0,name);
    if (!long.has(name)) assert.ok(ms<=300,name);
  }
  assert.equal(roots['--bt-ease-out'],'cubic-bezier(0.23, 1, 0.32, 1)');
  assert.equal(roots['--bt-ease-travel'],'cubic-bezier(0.77, 0, 0.175, 1)');
  assert.equal(roots['--bt-ease-drawer'],'cubic-bezier(0.32, 0.72, 0, 1)');
  assert.deepEqual(inspectSource(MOTION_OWNER,css),{});
  for (const source of [':root {--bt-motion-private:150ms;}', ':root {--ds-motion-private:150ms;}', '@theme {--ease-private:cubic-bezier(.23,1,.32,1);}', ':root {--ds-motion-fast:100ms;}']) assert.ok(inspectSource('web/styles/tokens.css',source)['bt-motion-owner'],source);
  assert.ok(inspectSource('web/features/review/styles.css',':root {--bt-motion-fast:150ms;}')['bt-motion-owner']);
});

test('canonical curve ownership never permits a slow-start response token', () => {
  const response = curve => `:root { --bt-ease-response: ${curve}; } @layer components { :where(.bt-menu) { transition-timing-function: var(--bt-ease-response); } }`;
  for (const curve of ['ease-in', 'EASE-IN']) assert.ok(inspectSource(MOTION_OWNER, css + response(curve))['bt-slow-start'], curve);
  assert.deepEqual(inspectSource(MOTION_OWNER, css + response('cubic-bezier(.23,1,.32,1)')), {});
});

test('four logical sheet forms, reversible fold and non-inheriting reduction are shared', () => {
  for (const name of ['bt-sheet-bottom','bt-sheet-end','bt-sheet-responsive','bt-sheet-phone']) assert.ok(css.includes(name));
  assert.ok(css.includes(':dir(rtl)'));
  assert.ok(css.includes('@media (min-width: 851px)'));
  assert.ok(css.includes('@media (max-width: 850px)'));
  for (const value of ['0fr','1fr']) assert.ok(css.includes(`grid-template-rows: ${value}`));
  for (const name of ['animation','transition','iterations']) assert.ok(css.includes(`@property --bt-motion-kept-${name} { syntax: "*"; inherits: false; }`));
  assert.ok(css.includes('--bt-motion-kept-animation: var(--bt-motion-gentle)'));
  assert.ok(css.includes('--bt-motion-kept-transition: var(--bt-motion-gentle)'));
  assert.ok(css.includes('animation-name: bt-fade-in; transform: none'));
  assert.ok(css.includes('transition-property: opacity; transform: none'));
  assert.ok(css.includes('@starting-style'));
  assert.ok(css.includes('data-starting'));
  const surfaces=entries.filter(entry=>entry.context.includes('@layer components') && /\.bt-(?:popover|menu|window|shade|sheet-)/.test(entry.context.at(-1)));
  assert.ok(surfaces.some(entry=>entry.prop==='transition'));
  assert.ok(surfaces.every(entry=>!entry.prop.startsWith('animation')), 'Reversible surfaces must retarget transitions, not restart frames.');
  assert.ok(surfaces.filter(entry=>entry.prop==='transform-origin' && /\.bt-popover/.test(entry.context.at(-1))).every(entry=>entry.value==='var(--radix-popper-transform-origin)'));
  assert.ok(surfaces.some(entry=>entry.prop==='transition-duration' && entry.value==='var(--bt-motion-overlay)' && entry.context.at(-1).includes('.bt-shade[data-drag-leave]')));
});

test('only the exact shared fold context, endpoints and transition shape may move layout', () => {
  assert.deepEqual(inspectSource(MOTION_OWNER, css), {});
  const privatePanel = '@layer components { :where(.bt-private-panel) { grid-template-rows:20px; transition:grid-template-rows var(--bt-motion-menu) var(--bt-ease-out); } }';
  for (const source of [
    css + privatePanel,
    css.replace(':where(:where(.bt-fold)) {', ':where(:where(.bt-fold), .bt-private-panel) {'),
    css.replace('grid-template-rows: 0fr', 'grid-template-rows: 20px'),
    css.replace('grid-template-rows: 1fr', 'grid-template-rows: auto'),
    css.replace('grid-template-rows var(--bt-motion-menu) var(--bt-ease-out)', 'grid-template-rows var(--bt-motion-fast) var(--bt-ease-out)'),
  ]) assert.ok(inspectSource(MOTION_OWNER, source)['bt-reflow-motion']);
  const privateFold = privatePanel.replace('20px', '0fr');
  assert.ok(inspectSource(MOTION_OWNER, css + privateFold)['bt-fold-detour']);
  assert.ok(inspectSource('web/styles/not-the-owner.css', privateFold)['bt-reflow-motion']);
});

test('new frames only composite and pointer hover never replays a glyph arc', () => {
  for (const entry of entries.filter(entry => entry.context.some(part => part.startsWith('@keyframes')))) assert.ok(['transform','opacity'].includes(entry.prop),entry.prop);
  assert.ok(!/will-change|requestAnimationFrame|:hover[^{}]*\{[^}]*animation:/.test(css));
  assert.ok(css.includes('@media (hover: hover) and (pointer: fine)'));
  assert.ok(css.includes('data-bt-motion-input="keyboard"'));
  assert.ok(css.includes('data-bt-motion="off"'));
  const globals=readFileSync(join(ROOT,'web/app/globals.css'),'utf8');
  assert.ok(globals.indexOf('styles/motion.css')<globals.indexOf('styles/bt-motion.css'));
  assert.equal((globals.match(/styles\/bt-motion\.css/g)??[]).length,1);
});
test('keyboard and off floors suppress host and descendant pseudo motion without retiming pointer halos', () => {
  const targets = entry => splitOutside(entry.context[0], /,/).flatMap(branch => {
    const match = /^:where\((.*)\)([^()]*)$/.exec(branch);
    assert.ok(match, branch);
    return splitOutside(match[1], /,/).map(scope => scope + match[2]);
  });
  const floor = entries.filter(entry => entry.context.length === 1 && entry.context[0].includes('[data-bt-motion-input="keyboard"]'));
  for (const scope of ['[data-bt-motion-input="keyboard"]', '[data-bt-motion="off"]']) {
    for (const descendant of ['', ' *']) for (const pseudo of ['', '::before', '::after']) {
      const target = scope + descendant + pseudo;
      assert.ok(floor.some(entry => entry.prop === 'animation' && entry.value === 'none' && targets(entry).includes(target)), `${target}: animation must be off`);
      assert.ok(floor.some(entry => entry.prop === 'transition-duration' && motionTokenMs(entry.value, roots) === 0 && targets(entry).includes(target)), `${target}: transition must be immediate`);
    }
  }
  const halo = entries.find(entry => entry.context.at(-1) === ':where(:where(.bt-nav-icon))::before' && entry.prop === 'transition');
  assert.equal(halo.value, 'opacity var(--bt-motion-fast) var(--bt-ease-colour)');
  assert.equal(motionTokenMs('var(--bt-motion-fast)', roots), 150);
  assert.ok(floor.every(entry => !targets(entry).some(target => target.includes('pointer'))), 'Pointer halos keep their ordinary 150ms step.');
});
function zeroHost(selector) {
  if (!selector.startsWith(':where(')) return false;
  let depth=1, at=7;
  for (;at<selector.length&&depth;at++) {if(selector[at]==='(')depth++;if(selector[at]===')')depth--;}
  return depth===0 && /^(?:::before|::after)?$/.test(selector.slice(at));
}
test('component recipe hosts have zero specificity, including state and hover conditions', () => {
  const selectors=new Set(entries.filter(entry => entry.context.includes('@layer components')).map(entry => entry.context.at(-1)));
  for (const selector of selectors) for (const branch of splitOutside(selector,/,/)) assert.ok(zeroHost(branch),branch);
  assert.equal(zeroHost(':where(.bt-window)[data-state="open"]'),false);
  assert.equal(zeroHost(':where(.bt-window[data-state="open"])'),true);
});

test('the original motion sheet is exact-hash-only and is never another new keyframe owner', () => {
  const file=join(ROOT,LEGACY_MOTION_OWNER);
  if (!existsSync(file)) {assert.deepEqual(motionRetirementIssues(),[]);return;}
  const source=readFileSync(file,'utf8');
  assert.equal(hashSource(source),LEGACY_MOTION_HASH);
  assert.equal(inspectSource(LEGACY_MOTION_OWNER,source)['bt-motion-legacy']??0,0);
  assert.equal(inspectSource(LEGACY_MOTION_OWNER,source)['bt-motion-owner']??0,0);
  assert.ok(inspectSource(LEGACY_MOTION_OWNER,source+'\n/* edited */')['bt-motion-legacy']);
  assert.ok(inspectSource('web/styles/not-the-owner.css',source)['bt-motion-owner']);
  assert.ok(inspectSource(LEGACY_MOTION_OWNER,'/* emptied */')['bt-motion-legacy']);
});

test('exact HEAD consumers may remain; changed bytes, copied paths and class recipes may not grow legacy use', () => {
  const directory=mkdtempSync(join(ROOT,'.bt-motion-probe-'));
  const write=(file,text)=>{mkdirSync(dirname(join(directory,file)),{recursive:true});writeFileSync(join(directory,file),text);};
  try {
    const file='packages/ui/src/index.tsx';
    const source=execFileSync('git',['show',`HEAD:${file}`],{cwd:ROOT,encoding:'utf8'});
    write(file,source);
    assert.equal(census(directory)[file].counts['bt-motion-legacy']??0,0);
    const changed=source+'\nexport const oldMotionClass="pg-row";\n';
    write(file,changed);
    assert.ok(census(directory)[file].counts['bt-motion-legacy']);
    write('web/features/review/copied.tsx',changed);
    assert.ok(census(directory)['web/features/review/copied.tsx'].counts['bt-motion-legacy']);
    write(file,changed.replaceAll('pg-','bt-').replaceAll('ui-image-frame-','bt-image-'));
    assert.equal(census(directory)[file].counts['bt-motion-legacy']??0,0);
    assert.ok(inspectSource('web/features/review/variants.ts','export const recipe=cva("pg-popover");')['bt-motion-legacy']);
    for (const frame of ['pg-fadeOut','pg-icon-wave','bt-drawer-in-rtl','psb-drawer-out','sx-progress','pg-face-in','proto-set-flash']) {
      assert.ok(inspectSource('web/features/review/styles.css',`.a {--frame:${frame};animation:var(--frame) var(--bt-motion-fast);}`)['bt-motion-legacy'],frame);
      assert.ok(inspectSource('web/features/review/frames.ts',`export const animationName="${frame}";`)['bt-motion-legacy'],frame);
    }
  } finally {rmSync(directory,{recursive:true,force:true});}
});

test('retirement waits for the final consumer and removes the compatibility import too', () => {
  const directory=mkdtempSync(join(ROOT,'.bt-motion-probe-'));
  const write=(file,text)=>{mkdirSync(dirname(join(directory,file)),{recursive:true});writeFileSync(join(directory,file),text);};
  try {
    write('web/features/review/styles.css','.pg-popover {opacity:1;}');
    assert.ok(motionRetirementIssues(directory).some(line=>line.includes('last consumer')));
    write(LEGACY_MOTION_OWNER,'/* present */');
    assert.deepEqual(motionRetirementIssues(directory),[]);
    unlinkSync(join(directory,LEGACY_MOTION_OWNER));
    write('web/features/review/styles.css','.bt-popover {opacity:1;}');
    write('web/app/globals.css','@import "../styles/motion.css";');
    assert.ok(motionRetirementIssues(directory).some(line=>line.includes('stylesheet import')));
    write('web/app/globals.css','@import "../styles/bt-motion.css";');
    assert.deepEqual(motionRetirementIssues(directory),[]);
  } finally {rmSync(directory,{recursive:true,force:true});}
});

test('only the two declared motion subpaths extend the public component boundary', () => {
  const manifest=JSON.parse(readFileSync(join(ROOT,'packages/ui/package.json'),'utf8'));
  assert.equal(manifest.exports['./motion'],'./src/motion-tokens.ts');
  assert.equal(manifest.exports['./motion-easing'],'./src/motion-easing.ts');
  for (const specifier of ['@beirut-time/ui/motion','@beirut-time/ui/motion-easing']) assert.equal(inspectSource('web/features/review/reader.ts',`import {readMotionToken} from "${specifier}";`)['bt-control-detour']??0,0);
  assert.ok(inspectSource('web/features/review/reader.ts','import {read} from "@beirut-time/ui/private-motion";')['bt-control-detour']);
});

test('old pacing and persistence statements stay exact alongside explicit supersession guards', () => {
  const source=readFileSync(join(ROOT,'web/shell/theme-provider.tsx'),'utf8');
  const tree=ts.createSourceFile('theme-provider.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX), effects=[];
  let cycle;
  const visit=node=>{
    if (ts.isVariableDeclaration(node)&&node.name.getText(tree)==='cycleTheme') cycle=node.initializer.arguments[0];
    if (ts.isCallExpression(node)&&node.expression.getText(tree)==='React.useEffect') effects.push(node.getText(tree));
    ts.forEachChild(node,visit);
  };
  visit(tree);
  const declarations=cycle.body.statements.filter(ts.isVariableStatement).flatMap(statement=>[...statement.declarationList.declarations]);
  const value=name=>declarations.find(node=>node.name.getText(tree)===name).initializer.getText(tree);
  const branch=cycle.body.statements.find(ts.isIfStatement);
  let callback;
  const find=node=>{if(ts.isCallExpression(node)&&node.expression.getText(tree)==='doc.startViewTransition')callback=node.arguments[0];ts.forEachChild(node,find);};
  find(branch.thenStatement);
  const strip=(statements,guard)=>statements.filter(node=>node.getText(tree).replace(/\s+/g,'')!==guard).map(node=>node.getText(tree)).join('\n');
  // Only these two added ownership operations are excluded from the old-facts
  // fingerprint. Focused provider tests exercise both real entry points.
  assert.ok(callback.body.statements.some(node=>node.getText(tree).replace(/\s+/g,'')==='if(!intent.isCurrent())return;'));
  assert.ok(value('intent').startsWith('beginThemeIntent('));
  const parts=[...effects,value('next'),value('doc'),branch.expression.getText(tree),strip(callback.body.statements,'if(!intent.isCurrent())return;'),strip(branch.elseStatement.statements,'intent.release();')];
  const compiled=parts.map(text=>ts.transpileModule(text,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext,removeComments:true}}).outputText);
  assert.equal(effects.length,1);assert.equal(parts.length,6);
  assert.equal(hashSource(JSON.stringify(compiled)),'0c9fd2d3271f768a9560673cbc57b88c115f4121e92667173519f4e951d61119');
});

test('the owner migration does not increase or rehash any accepted main debt', async () => {
  assert.deepEqual(await measureReference(),JSON.parse(readFileSync(join(ROOT,LEDGER),'utf8')));
});
