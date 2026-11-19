import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { readFileSync } from 'node:fs';
import { recovery } from './recovery';
import { copy } from './copy';
import { Textarea } from '@beirut-time/ui/foundation';

describe('private import recovery',()=>{
 it('retains the operation after unknown or unavailable responses',()=>{
  for(const status of [undefined,408,429,500,502,503,504])expect(recovery(status)).toBe('retry');
 });
 it('allows correcting definitively rejected tables',()=>{
  for(const status of [400,409,413,422])expect(recovery(status)).toBe('correct');
 });
 it('clears private state when access is lost',()=>{
  expect(recovery(401)).toBe('clear');expect(recovery(403)).toBe('clear');
 });
 it('keeps exact mixed-script input for both language labels',()=>{
  const value='ساعة ⌚ Sample,5000.00,S1';
  for(const locale of ['en','ar'] as const){
   const html=renderToStaticMarkup(createElement(Textarea,{id:'private-table',label:copy[locale].table,value}));
   expect(html).toContain(value);expect(html).toContain('id="private-table"');
  }
  const source=readFileSync(new URL('./view.tsx',import.meta.url),'utf8');
  expect(source).toContain('<ImportForm key={scope}');
  expect(source).toContain("const scope=(session?.access_fingerprint ?? '')+':'+organization");
  expect(source).not.toMatch(/localStorage|sessionStorage|document\.cookie/);
 });
});
