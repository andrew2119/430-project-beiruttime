import { expect, it } from 'vitest';
import { validateRegistrations } from '../registry-loader';
import type { Registration } from '../registry-types';
const entry=(lane:`L${string}`, namespace:string, path:string):Registration=>({lane,namespace,routes:[{path,roles:['public'],area:'storefront'}],dictionaries:{en:{title:'Title'},ar:{title:'عنوان'}}});
it('admits concurrent L12 and L25 tabs without changing legacy tabs',()=>{
  const entries=[entry('L00','old','/old'),entry('L12','policy','/policy'),entry('L25','fit','/fit')];
  expect(validateRegistrations(entries)).toBe(entries);
});
it('admits explicitly registered v2 paths while preserving the fixed version boundary',()=>{
  expect(()=>validateRegistrations([{...entry('L12','policy','/policy'),gateway:[{service:'auction',path:'/v2/auctions/:id',methods:['GET'],roles:['public']}]}])).not.toThrow();
  for(const path of ['/internal/v2/auctions','/v0/auctions','/v3/auctions','https://other.test/v2/auctions','/v2/../admin','/v2/auctions?admin=1','/v2/auctions#admin'])
    expect(()=>validateRegistrations([{...entry('L12','policy','/policy'),gateway:[{service:'auction',path,methods:['GET'],roles:['public']}]}])).toThrow();
});
it('preserves lane, URL, namespace, dictionary and gateway safeguards',()=>{
  expect(()=>validateRegistrations([entry('L26','bad','/bad')])).toThrow();
  expect(()=>validateRegistrations([entry('L12','policy','/same'),entry('L25','fit','/same')])).toThrow();
  expect(()=>validateRegistrations([entry('L12','policy','/one'),entry('L25','policy','/two')])).toThrow();
  expect(()=>validateRegistrations([{...entry('L12','policy','/one'),dictionaries:{en:{title:'Title'},ar:{}}}])).toThrow();
  expect(()=>validateRegistrations([{...entry('L12','policy','/one'),gateway:[{service:'auction',path:'/v1/../admin',methods:['GET'],roles:['public']}]}])).toThrow();
});
