import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { buyerCommand, decodeHistory, decodeRecord, reference, ReceiptAttempt } from '../../../../web/features/custody/model';
import { copy } from '../../../../web/features/custody/copy';
import CustodyView from '../../../../web/features/custody/view';
import { LocaleContext } from '../../../../web/shell/locale-context';

const record = {
  schema_version:'custody.v1',subject_id:'order',operation_id:'prepare',watch_id:'watch',revision:1,
  state:'prepared',route:'dealer',held:false,pending_reason:null,next_actor:null,next_review_at:null,
  buyer_received_at:null,dispute_deadline:null,window_hours:null,custodian:'seller',
  due_actions:[],
  current:{watch_id:'watch',watch_revision:1,source_revision:1,quote_id:'quote',quote_revision:1,
    policy_revision:1,actor_id:'buyer',organization_id:null},
};
const envelope = (row:unknown) => ({schema_version:'custody.v1',result:row});

describe('custody read contract',()=>{
  it('accepts a missing record without inventing receipt',()=>{
    expect(decodeRecord(envelope(null),'order')).toBeNull();
    expect(decodeRecord(envelope(record),'order')?.buyer_received_at).toBeNull();
  });
  it('rejects another order and watch',()=>{
    expect(()=>decodeRecord(envelope(record),'other')).toThrow();
    expect(()=>decodeRecord(envelope({...record,watch_id:'other'}),'order')).toThrow();
  });
  it.each([NaN,Infinity,-1,1.5])('rejects invalid revision %s',revision=>{
    expect(()=>decodeRecord(envelope({...record,revision}),'order')).toThrow();
  });
  it('rejects receipt without its full accepted window',()=>{
    expect(()=>decodeRecord(envelope({...record,state:'received'}),'order')).toThrow();
    expect(()=>decodeRecord(envelope({...record,state:'received',buyer_received_at:'2026-11-17T12:00:00Z',dispute_deadline:'2026-11-20T12:00:00Z',window_hours:72}),'order')).toThrow();
  });
  it.each([['private',72],['dealer',168],['brand',168],['job',168]])('uses the %s accepted window', (route,hours)=>{
    const receipt = '2026-11-17T12:00:00Z';
    const row = {...record,state:'received',route,buyer_received_at:receipt,window_hours:hours,
      dispute_deadline:new Date(Date.parse(receipt)+Number(hours)*3600000).toISOString()};
    expect(decodeRecord(envelope(row),'order')?.window_hours).toBe(hours);
  });
  it('requires a next responsible party on every hold',()=>{
    expect(()=>decodeRecord(envelope({...record,held:true}),'order')).toThrow();
  });
  it('keeps the original operation, data and dollar-free proof unchanged across locales',()=>{
    const decoded = decodeRecord(envelope(record),'order')!;
    const proof = {watch_id:'watch',recipient:'buyer',condition:'حالة agreed ⌚',accessories:['box'],
      location:'Beirut',address:'عنوان Address',received_at:'2026-11-17T12:00:00Z',
      signed_handoff:true as const,source:'buyer_acknowledgement' as const};
    const command = buyerCommand(decoded,proof,'stable');
    expect(JSON.stringify(command)).toBe(JSON.stringify(buyerCommand(decoded,proof,'stable')));
    expect(command.proof.condition).toBe(proof.condition);
    expect(command.expected_revision).toBe(1);
  });
  it('bounds references and proofs',()=>{
    expect(reference('x'.repeat(100))).toBe(true);
    expect(reference('x'.repeat(101))).toBe(false);
    expect(reference('../other')).toBe(false);
  });
  it('retains exact pending bytes when a record disappears or another order is chosen',()=>{
    const owner = new ReceiptAttempt();
    const decoded = decodeRecord(envelope(record),'order')!;
    const proof = {watch_id:'watch',recipient:'buyer',condition:'agreed',accessories:[],location:'Beirut',address:'address',received_at:'2026-11-17T12:00:00Z',signed_handoff:true as const,source:'buyer_acknowledgement' as const};
    const command = buyerCommand(decoded,proof,'stable');
    const initial = owner.capture(command);
    command.proof.condition = 'edited';
    expect(owner.capture()).toBe(initial);
    expect(owner.capture({...command,subject_id:'other',operation_id:'new'})).toBe(initial);
    expect(JSON.parse(initial!.body).proof.condition).toBe('agreed');
    expect(owner.unresolved()).toBe(true);
    owner.clear();
    expect(owner.capture()).toBeNull();
  });
  it('preserves server totals for zero, one and a thousand records',()=>{
    for (const total of [0,1,1000]) {
      const items = Array.from({length:Math.min(total,25)},(_,index)=>({operation_id:`operation-${index}`,revision:total-index,state:'prepared',held:false,buyer_received_at:null,dispute_deadline:null}));
      expect(decodeHistory(envelope({subject_id:'order',items,total,offset:0,limit:25}),'order',0).total).toBe(total);
    }
  });
  it('rejects cross-order history and partial totals',()=>{
    expect(()=>decodeHistory(envelope({subject_id:'other',items:[],total:0,offset:0,limit:25}),'order',0)).toThrow();
    expect(()=>decodeHistory(envelope({subject_id:'order',items:[record],total:0,offset:0,limit:25}),'order',0)).toThrow();
  });
});

describe('bilingual private entry',()=>{
  it.each(['en','ar'] as const)('renders a private sign-in state in %s',locale=>{
    const html = renderToStaticMarkup(<LocaleContext.Provider value={locale}><CustodyView/></LocaleContext.Provider>);
    expect(html).toContain(copy[locale].title);
    expect(html).toContain(copy[locale].signIn);
    expect(html).not.toContain('buyer_received_at');
  });
  it('has matching states, incident reasons and recovery copy',()=>{
    expect(Object.keys(copy.en)).toEqual(Object.keys(copy.ar));
    expect(Object.keys(copy.en.states)).toEqual(Object.keys(copy.ar.states));
    expect(Object.keys(copy.en.reasons)).toEqual(Object.keys(copy.ar.reasons));
    for (const locale of ['en','ar'] as const) for (const value of Object.values(copy[locale])) {
      if (typeof value === 'string') expect(value.length).toBeGreaterThan(0);
    }
  });
});
