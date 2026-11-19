import { describe, it, expect, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import source from '../../../../packages/contracts-service/reduction/fixtures/success.json';
import { measurement, recordRead, send, validReference } from '../../../../web/features/reduction/api';
import { copy } from '../../../../web/features/reduction/copy';
import type { ReductionCommand } from '../../../../packages/contracts-service/reduction/v1';
const state=vi.hoisted(()=>({locale:'en' as 'en'|'ar',answer:{} as unknown,error:null as unknown,request:vi.fn()}));
vi.mock('@/features/identity/session',()=>({authenticatedRequest:(...args:unknown[])=>state.request(...args),useSession:()=>null,useSessionState:()=> 'signed-out'}));
vi.mock('@/shell/locale-context',()=>({useLocale:()=>state.locale}));
vi.mock('@/lib/page-speed/read',()=>({usePageRead:()=>({data:state.answer,isPending:false,error:state.error})}));
import { ApiError } from '../../../../web/lib/api/client';
import { RecordForm } from '../../../../web/features/reduction/view';

describe('reduction',()=>{
  it('retains exact measurements and rejects ambiguity',()=>{
    expect(measurement('17.5','cm')).toBe(true);
    expect(measurement('175','mm')).toBe(true);
    for(const value of ['17,5','17.55','NaN','Infinity','0','351','175 '])expect(measurement(value,'mm')).toBe(false);
    expect(measurement('80','mm')).toBe(true);expect(measurement('350','mm')).toBe(true);
  });
  it('partitions current reads and never warms private data on intent',()=>{
    const read=recordRead('record','business','access');
    expect(read.key).toEqual(['reduction.v1','access','business','record']);
    expect(read.warm).toBe('open-only');expect(read.fresh).toBe(0);
    expect(validReference(source.command.operation_id)).toBe(true);
    expect(validReference('../private')).toBe(false);
  });
  it('retries identical commands with the same reference',async()=>{
    const body=source.command as ReductionCommand;
    state.request.mockResolvedValue({});
    await send('record','access',body);await send('record','access',body);
    const calls=state.request.mock.calls.slice(-2);
    expect(calls[0]).toEqual(calls[1]);expect(JSON.parse(calls[0][1].body).operation_id).toBe(body.operation_id);
    expect(calls[0][1].accessFingerprint).toBe('access');
  });
  it.each(['en','ar'] as const)('renders supported choices, target and recovery in %s',locale=>{
    state.locale=locale;
    state.answer={record:null,context:{...source.authority,permission:'buyer_request'}};
    const markup=renderToStaticMarkup(<RecordForm binding={{record:'r',organization:'o'}} access="a" onPending={()=>{}}/>);
    expect(markup).toContain(copy[locale].target);
    expect(markup).toContain(copy[locale].recipient);
    expect(markup).toContain(copy[locale].refresh);
    expect(markup).not.toContain('<main');
  });
  it.each(['en','ar'] as const)('shows unresolved actual parts and recipient in %s',locale=>{
    state.locale=locale;
    state.answer={record:{...source.command,state:'unresolved',revision:2,removed_count:1,returned_count:0},context:source.authority};
    const markup=renderToStaticMarkup(<RecordForm binding={{record:'r',organization:'o'}} access="a" onPending={()=>{}}/>);
    expect(markup).toContain(copy[locale].unresolvedBody);
    expect(markup).toContain(source.command.recipient_id);
    expect(markup).toContain(copy[locale].returned);
    expect(markup).toContain(`href="/${locale}/inbox"`);
    expect(markup).toContain(copy[locale].support);
  });
  it.each(['en','ar'] as const)('offers support after denied access in %s',locale=>{
    state.locale=locale;
    state.answer=undefined;
    state.error=new ApiError(403,'denied','reduction-test');
    const markup=renderToStaticMarkup(<RecordForm binding={{record:'r',organization:'o'}} access="a" onPending={()=>{}}/>);
    expect(markup).toContain(copy[locale].denied);
    expect(markup).toContain(`href="/${locale}/inbox"`);
    expect(markup).toContain(copy[locale].support);
    state.error=null;
  });
});
