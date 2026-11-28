import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import type { Command, Context } from '@contracts/contracts-trust/disputes/v1';
import { DisputeFields } from './fields';
import { dollars, type Draft } from './model';
import { copy } from './copy';

const context:Context={source_revision:1,assignment_revision:1,expected_revision:2,principal_minor:500000,closing_at:'2026-11-20T00:00:00Z',actions:['refund','release'],case:null};
const operation:Command={schema_version:'disputes.v1',operation_id:'retained_operation',subject_id:'order_1',organization_id:null,expected_revision:2,source_revision:1,assignment_revision:1,kind:'refund',reason:'Mixed العربية ⌚',evidence:[],amount_minor:500000};

describe('private dispute fields',()=>{
 it('retains exact inputs, selected private file and pending reference across presentation changes',()=>{
  const file=new File(['private bytes'],'دليل-private.pdf',{type:'application/pdf'});
  const draft:Draft={reason:'Mixed العربية ⌚ '.repeat(100),amount:'٥٠٠٠٫٠٠',file,operation};
  const changes:Draft[]=[];
  const render=(locale:'en'|'ar')=>renderToStaticMarkup(createElement(DisputeFields,{locale,draft,onDraft:value=>changes.push(value),kind:'refund',onKind:()=>{throw new Error('Unexpected change');},context,locked:true,fileInput:null,onSubmit:()=>{throw new Error('Unexpected submit');}}));
  for(const locale of ['en','ar','en'] as const) {
   const html=render(locale);
   expect(html).toContain(draft.reason);
   expect(html).toContain('٥٠٠٠٫٠٠');
   expect(html).toContain('retained_operation');
   expect(html).toContain(file.name);
   expect(html).not.toContain('private bytes');
   expect(html).toContain(copy[locale].submit);
   expect(draft.file).toBe(file);
   expect(draft.operation).toBe(operation);
  }
  expect(changes).toEqual([]);
 });
 it('keeps the native file control and private form identity independent of language',()=>{
  const screen=readFileSync(new URL('./screen.tsx',import.meta.url),'utf8');
  const fields=readFileSync(new URL('./fields.tsx',import.meta.url),'utf8');
  expect(screen).toContain('key={session.access_fingerprint}');
  expect(screen).not.toMatch(/key=\{locale\}|key=\{.*language/);
  expect(fields).not.toContain('key=');
  expect(fields).toContain('type="file"');
  expect(fields).not.toMatch(/(?:localStorage|sessionStorage|document\.cookie)/);
 });
 it('clears the private subtree for command, recovery, read and download denials',()=>{
  const screen=readFileSync(new URL('./screen.tsx',import.meta.url),'utf8');
  expect(screen).toContain('return denied?<State');
  expect(screen).toContain(':<PrivateForm scope={scope} onDenied={deny}/>');
  expect(screen).toContain('onDenied(operationReference.current);return;');
  expect(screen).toContain('onDenied(current.operation_id)');
  expect(screen).toContain("query.error.status===403||query.error.code==='denied'");
  expect(screen).toContain("cause.status===403||cause.code==='denied'))onDenied();");
  expect(screen).toContain('return ()=>controller.abort()');
 });
 it('resends fixed submissions independently of earlier results and uses canonical composition',()=>{
  const screen=readFileSync(new URL('./screen.tsx',import.meta.url),'utf8');
  expect(screen).toContain('const answer=await send(scope,body,signal);');
  expect(screen).not.toContain('retry&&result');
  expect(screen).toContain("from '@/shell/foundation/page'");
  expect(screen).toContain('<PageBody>');
  expect(screen).toContain('context.case?.decision?.evidence');
 });
 it('uses exact integer cents for either digit presentation',()=>{
  expect(dollars('5000.00')).toBe(500000);
  expect(dollars('٥٠٠٠٫٠٠')).toBe(500000);
  for(const value of ['1.001','-1','NaN','Infinity','1e3'])expect(dollars(value)).toBeNull();
 });
 it('has complete corresponding recovery states in both languages',()=>{
  expect(Object.keys(copy.en).sort()).toEqual(Object.keys(copy.ar).sort());
  expect(Object.keys(copy.en.states).sort()).toEqual(Object.keys(copy.ar.states).sort());
 });
});
