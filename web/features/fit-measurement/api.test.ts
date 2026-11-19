import { beforeEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import type { FitCommand, FitRecord } from '@contracts/contracts-service/fit-measurement/v1';
const request=vi.hoisted(()=>vi.fn());
vi.mock('@/features/identity/session',()=>({authenticatedRequest:request}));
import { contextRead, contextKey, parseContext, readContext, saveMeasurement } from './api';
const fixture=JSON.parse(readFileSync(new URL('../../../packages/contracts-service/fit-measurement/fixtures.json',import.meta.url),'utf8')) as {command:FitCommand;record:FitRecord};
const scope={subject_id:fixture.command.subject_id,watch_id:fixture.command.watch_id,organization_id:fixture.command.organization_id};
beforeEach(()=>request.mockReset());
it('binds reads to scope and access, never locale',async()=>{
  const answer={...scope,source_revision:1,record:fixture.record};
  request.mockResolvedValue(answer);
  expect(await readContext(scope,'current',new AbortController().signal)).toEqual(answer);
  expect(contextKey(scope,'current')).not.toEqual(contextKey(scope,'other'));
  expect(request.mock.calls[0][1].accessFingerprint).toBe('current');
});
it('validates private context scope and final-fit distinction',()=>{
  expect(()=>parseContext({...scope,source_revision:1,record:{...fixture.record,final_fit_pass:true} as unknown as FitRecord},scope)).toThrow();
  expect(()=>parseContext({...scope,watch_id:'other',source_revision:1,record:null},scope)).toThrow();
});
it('retries the exact command and rejects unbound success',async()=>{
  request.mockResolvedValue(fixture.record);
  const signal=new AbortController().signal;
  await saveMeasurement(fixture.command,'current',signal);
  await saveMeasurement(fixture.command,'current',signal);
  expect(request.mock.calls[0][1].body).toBe(request.mock.calls[1][1].body);
  request.mockResolvedValue({...fixture.record,operation_id:'00000000-0000-4000-8000-000000000099'});
  await expect(saveMeasurement(fixture.command,'current',signal)).rejects.toThrow();
});

it('shares the mounted question with an opening-only current read',async()=>{
  const answer={...scope,source_revision:1,record:fixture.record};
  request.mockResolvedValue(answer);
  const read=contextRead(scope,'current');
  expect(read.key).toEqual(contextKey(scope,'current'));
  expect(read.warm).toBe('open-only');
  expect(read.fresh).toBe(0);
  expect(await read.ask(new AbortController().signal)).toEqual(answer);
});

it('declares the private page with its owned shared view and read identity',()=>{
  const declaration=JSON.parse(readFileSync(new URL('./delivery-contract.json',import.meta.url),'utf8'));
  expect(declaration).toEqual({
    route:'/care/fit',
    file:'web/app/(fit-measurement)/care/fit/page.tsx',
    view:'web/features/fit-measurement/view.tsx',
    kind:'reads',
    reason:expect.any(String),
    content:'[data-page-answer]',
    read:String(contextKey(scope,'current')[0]),
    proof:'owed',
  });
  const view=readFileSync(new URL('./view.tsx',import.meta.url),'utf8');
  expect(view).toContain('<PageFrame>');
  expect(view).toContain('<PageHeader ');
  expect(view).toContain('usePageRead(contextRead(scope,access))');
});
