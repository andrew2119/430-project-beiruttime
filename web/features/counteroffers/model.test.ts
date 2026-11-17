import { describe, expect, it } from 'vitest';
import { dollars, permissionDenied, termsMatch } from './model';
import { copy } from './copy';

describe('exact dollar entry',()=>{
  it.each([['5000',500000],['0.01',1],['1.5',150],['90000000000',9000000000000]])('parses %s without rounding',(value,expected)=>{
    expect(dollars(String(value))).toBe(expected);
  });
  it.each(['0','-1','1.001','1e4','Infinity','1,000',' 1','١٢','90000000001','😀'])('refuses %s',value=>{
    expect(dollars(value)).toBeNull();
  });
  it('provides both languages for every recovery and commercial label',()=>{
    expect(Object.keys(copy.ar).sort()).toEqual(Object.keys(copy.en).sort());
    for(const text of Object.values(copy.ar))expect(text).toMatch(/[\u0600-\u06ff]/);
  });
});

const economics={quote_id:'quote',quote_revision:2,terms_revision:3,currency:'USD' as const,
  policy_revision:1,price_minor:100,buyer_fee_minor:3,seller_commission_minor:5,total_minor:103};
const terms={quote_id:'quote',quote_revision:2,terms_revision:3,
  en:{terms:'Exact terms',returns:'Return conditions',assurance:'Assurance conditions'},
  ar:{terms:'الشروط',returns:'شروط الإرجاع',assurance:'شروط الضمان'},support_href:'/support'};
it('requires complete bilingual terms bound to the exact retained quote',()=>{
  expect(termsMatch(terms,economics)).toBe(true);
  for(const changed of [undefined,{...terms,quote_revision:1},{...terms,terms_revision:1},
    {...terms,ar:{...terms.ar,returns:''}},{...terms,support_href:'//elsewhere'},
    {...terms,support_href:'/\\elsewhere'}])expect(termsMatch(changed,economics)).toBe(false);
});
it('distinguishes permission loss from temporary unavailability',()=>{
  for(const error of [{status:401},{status:403},{code:'denied'},{code:'forbidden'}])expect(permissionDenied(error)).toBe(true);
  expect(permissionDenied({status:503})).toBe(false);
});

it('never retains a counter from another subject or watch regardless of revision',async()=>{
  const {currentCounter,operationMatches}=await import('./model');
  const fixture=await import('../../../packages/contracts-pricing/counteroffers/fixtures/success.v1.json');
  const old={...fixture.current,revision:10} as import('@contracts/contracts-pricing/counteroffers').Counter;
  const next={...old,subject_id:'next',watch_id:'next-watch',revision:1};
  expect(currentCounter(next,old,false,next.subject_id,next.watch_id)).toBe(next);
  expect(currentCounter(old,old,false,next.subject_id,next.watch_id)).toBeNull();
  expect(currentCounter(null,old,false,next.subject_id,next.watch_id)).toBeNull();
  const command=fixture.command as import('@contracts/contracts-pricing/counteroffers').Command;
  const answer=fixture.operation as import('@contracts/contracts-pricing/counteroffers').Operation;
  expect(operationMatches(answer,command)).toBe(true);
  for(const field of ['subject_id','watch_id','actor_id','organization_id','expected_revision'] as const){
    expect(operationMatches({...answer,[field]:field==='expected_revision'?99:'other'},command)).toBe(false);
  }
});
