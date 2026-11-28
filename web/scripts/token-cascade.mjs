import assert from 'node:assert/strict';
import { cssDeclarations } from './check-ui-rules.mjs';

// A bounded source model for this token sheet, not a browser replacement. It
// supports its class/attribute/root, descendant, :is/:where and px media shapes;
// unsupported selectors/conditions fail instead of being silently discarded.
export function splitOutside(text, separator) {
  const result = []; let start = 0, depth = 0, quote = '';
  for (let at = 0; at <= text.length; at++) {
    const char = text[at];
    if (quote) { if (char === quote && text[at - 1] !== '\\') quote = ''; }
    else if (char === '"' || char === "'") quote = char;
    else if (char === '(' || char === '[') depth++;
    else if (char === ')' || char === ']') depth--;
    if (at === text.length || (!quote && depth === 0 && separator.test(char))) {
      const part = text.slice(start, at).trim();
      if (part) result.push(part);
      start = at + 1;
    }
  }
  assert.equal(depth, 0, `Unbalanced selector: ${text}`);
  return result;
}
const sum = (a, b) => a.map((value, index) => value + b[index]);
export const compareSpecificity = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
function compound(selector, node) {
  let rest = selector, matches = true, specificity = [0, 0, 0];
  while (rest) {
    const fn = /^:(is|where)\(/.exec(rest);
    if (fn) {
      let depth = 1, at = fn[0].length;
      for (; at < rest.length && depth; at++) { if (rest[at] === '(') depth++; if (rest[at] === ')') depth--; }
      assert.equal(depth, 0, selector);
      const choices = splitOutside(rest.slice(fn[0].length, at - 1), /,/).map(part => compound(part, node));
      matches &&= choices.some(choice => choice.matches);
      if (fn[1] === 'is') specificity = sum(specificity, choices.map(choice => choice.specificity).sort(compareSpecificity).at(-1));
      rest = rest.slice(at); continue;
    }
    const attr = /^\[([\w-]+)(?:=["']([^"']*)["'])?\]/.exec(rest);
    if (attr) {
      matches &&= Object.hasOwn(node.attrs ?? {}, attr[1]) && (attr[2] === undefined || node.attrs[attr[1]] === attr[2]);
      specificity[1]++; rest = rest.slice(attr[0].length); continue;
    }
    const className = /^\.([\w-]+)/.exec(rest);
    if (className) { matches &&= (node.classes ?? []).includes(className[1]); specificity[1]++; rest = rest.slice(className[0].length); continue; }
    if (rest.startsWith(':root')) { matches &&= !node.parent; specificity[1]++; rest = rest.slice(5); continue; }
    const tag = /^(?:[a-z][\w-]*|\*)/i.exec(rest);
    if (tag) { matches &&= tag[0] === '*' || tag[0] === node.tag; if (tag[0] !== '*') specificity[2]++; rest = rest.slice(tag[0].length); continue; }
    throw new Error(`Unsupported token selector: ${selector}`);
  }
  return { matches, specificity };
}
export function matchSelector(selector, node) {
  const matches = [];
  for (const branch of splitOutside(selector, /,/)) {
    const parts = splitOutside(branch, /\s/);
    const specificity = parts.reduce((total, part) => sum(total, compound(part, node).specificity), [0, 0, 0]);
    const path = (index, current) => {
      if (!current || !compound(parts[index], current).matches) return false;
      if (index === 0) return true;
      for (let parent = current.parent; parent; parent = parent.parent) if (path(index - 1, parent)) return true;
      return false;
    };
    if (path(parts.length - 1, node)) matches.push(specificity);
  }
  return matches.sort(compareSpecificity).at(-1) ?? null;
}
function activeMedia(condition, width) {
  const match = /^@media\s*\((max|min)-width:\s*([\d.]+)px\)$/.exec(condition);
  assert.ok(match, `Unsupported token condition: ${condition}`);
  return match[1] === 'max' ? width <= Number(match[2]) : width >= Number(match[2]);
}
function expand(value, env, seen = new Set()) {
  return value.replace(/var\(\s*(--[\w-]+)\s*\)/g, (original, name) => {
    if (!(name in env)) return original;
    assert.ok(!seen.has(name), `Cyclic token: ${name}`);
    return expand(env[name], env, new Set([...seen, name]));
  }).replace(/\s+/g, ' ').trim();
}
export function tokenCascade(source) {
  const declarations = cssDeclarations(source);
  return function compute(node, width = 1440) {
    // Parent values are already computed before inheritance; local variable
    // references resolve against this element's winning declarations only.
    const inherited = node.parent ? compute(node.parent, width) : {};
    const winners = new Map();
    for (const entry of declarations) {
      if (!entry.prop.startsWith('--') && entry.prop !== 'color-scheme') continue;
      let specificity;
      if (entry.context.length === 1 && /^@theme(?: inline)?$/.test(entry.context[0])) {
        // Virtual root exports model source references, not emitted utilities.
        if (node.parent) continue;
        specificity = [0, 0, 0];
      } else {
        if (!entry.context.slice(0, -1).every(condition => activeMedia(condition, width))) continue;
        specificity = matchSelector(entry.context.at(-1), node);
        if (!specificity) continue;
      }
      const before = winners.get(entry.prop);
      if (!before || compareSpecificity(specificity, before.specificity) >= 0) winners.set(entry.prop, {specificity, value:entry.value});
    }
    const env = {...inherited, ...Object.fromEntries([...winners].map(([name, entry]) => [name, entry.value]))};
    return Object.fromEntries(Object.entries(env).map(([name, value]) => [name, expand(value, env)]));
  };
}
