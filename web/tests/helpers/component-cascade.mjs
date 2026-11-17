import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const ROOT = fileURLToPath(new URL('../../../',import.meta.url));
const local = createRequire(new URL('../../package.json',import.meta.url)), parser = createRequire(local.resolve('next/package.json'))('postcss');
function cssDeclarations(source) {
  const result = [];parser.parse(source).walkDecls(node=>{const context = [];for (let parent = node.parent;parent?.parent;parent = parent.parent) context.unshift(parent.type === 'atrule' ? `@${parent.name} ${parent.params}`.trim() : parent.selector);result.push({prop:node.prop,value:node.value,context});});return result;
}
function splitOutside(text,separator) {
  let depth = 0, start = 0;const result = [];
  for (let at = 0;at <= text.length;at++) {if (text[at] === '(') depth++;if (text[at] === ')') depth--;if (at === text.length || depth === 0 && separator.test(text[at])) {const part = text.slice(start,at).trim();if (part) result.push(part);start = at+1;}}
  return result;
}
function matches(selector,node) {
  assert.ok(selector.startsWith(':where(') && selector.endsWith(')'),selector);
  return splitOutside(selector.slice(7,-1),/,/).some(branch=>{
    if (/\s/.test(branch)) return false;
    const classes = [...branch.matchAll(/\.([\w-]+)/g)].map(match=>match[1]);
    const attrs = [...branch.matchAll(/\[([\w-]+)="([^"]*)"\]/g)];
    assert.ok(branch.replace(/\.([\w-]+)/g,'').replace(/\[([\w-]+)="([^"]*)"\]/g,'') === '',branch);
    return classes.every(name=>node.classes.includes(name)) && attrs.every(match=>node.attrs[match[1]] === match[2]);
  });
}

// Bounded actual-import source model, not emitted CSS or browser certification.
const globals = readFileSync(resolve(ROOT,'web/app/globals.css'),'utf8');
const imports = [...globals.matchAll(/@import\s+"([^"]+)"/g)].map(match=>resolve(ROOT,'web/app',match[1])).filter(file=>/\/bt-(?:motion|components)\.css$/.test(file));
assert.equal(imports.length,2);
const entries = imports.flatMap(file=>cssDeclarations(readFileSync(file,'utf8')));
const tokens = Object.fromEntries(cssDeclarations(readFileSync(resolve(ROOT,'web/styles/tokens.css'),'utf8')).filter(entry=>entry.prop.startsWith('--bt-space-')).map(entry=>[entry.prop,entry.value]));
export function surfaceStyle(classes,state,form,width = 1200) {
  const node = {tag:'div',classes,attrs:{'data-state':state,...(form ? {'data-form':form} : {})}}, result = [];
  for (const entry of entries) {
    if (!['pointer-events','padding','padding-inline','padding-block','padding-left','padding-right'].includes(entry.prop) || !/\.bt-(?:surface-(?:shade|stage|panel)|shade|window)/.test(entry.context.at(-1))) continue;
    if (!entry.context.includes('@layer components')) continue;
    let active = true;
    for (const condition of entry.context.filter(part=>part.startsWith('@media'))) {
      const match = /^@media \((max|min)-width: (\d+)px\)$/.exec(condition);assert.ok(match,condition);
      active &&= match[1] === 'max' ? width <= Number(match[2]) : width >= Number(match[2]);
    }
    if (active && matches(entry.context.at(-1),node)) result.push(entry);
  }
  return result;
}
export function surfacePointer(classes,state,form,width) {return surfaceStyle(classes,state,form,width).filter(entry=>entry.prop === 'pointer-events').at(-1)?.value;}
export function surfacePadding(classes,form,width,dir,insets) {
  const edges = {left:0,right:0};
  const value = raw=>{
    let text = raw.replace(/var\((--[\w-]+)\)/g,(_,name)=>{assert.ok(name in tokens,name);return tokens[name];}).replace(/env\(safe-area-inset-(left|right|top|bottom),\s*0px\)/g,(_,side)=>`${insets[side] ?? 0}px`);
    text = text.replace(/max\(([^()]*)\)/g,(_,parts)=>`${Math.max(...parts.split(',').map(part=>Number.parseFloat(part)))}px`);
    assert.ok(/^\d+(?:\.\d+)?px$|^0$/.test(text),text);return Number.parseFloat(text);
  };
  for (const entry of surfaceStyle(classes,'open',form,width)) {
    const parts = splitOutside(entry.value,/\s/);
    if (entry.prop === 'padding') {edges.left = value(parts[3] ?? parts[1] ?? parts[0]);edges.right = value(parts[1] ?? parts[0]);}
    if (entry.prop === 'padding-inline') {edges[dir === 'rtl' ? 'right' : 'left'] = value(parts[0]);edges[dir === 'rtl' ? 'left' : 'right'] = value(parts[1] ?? parts[0]);}
    if (entry.prop === 'padding-left') edges.left = value(entry.value);
    if (entry.prop === 'padding-right') edges.right = value(entry.value);
  }
  return edges;
}
