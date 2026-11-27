import {describe,expect,it} from 'vitest';
import {failureRecovery} from './recovery';

describe('cancellation recovery',()=>{
 const privateAnswer={state:'accepted',refundable_minor:500000,next_review_at:'2026-11-18T00:00:00Z'};
 it.each([401,403])('clears a successful private read after access denial %s',status=>{
  const result=failureRecovery(status,true,privateAnswer);
  expect(result.outcome).toBeNull();
  expect(result.error).toBe('denied');
  expect(result.rejected).toBe(false);
 });
 it.each([403,409,422])('permits correction after definitive submission rejection %s',status=>{
  expect(failureRecovery(status,false,null)).toEqual({outcome:null,error:'denied',rejected:true});
 });
 it.each([null,503,504])('keeps uncertain delivery bound to its operation %s',status=>{
  expect(failureRecovery(status,false,null)).toEqual({outcome:null,error:'unavailable',rejected:false});
 });
 it.each([401,403,409,422])('retains an unresolved operation after rejection %s',status=>{
  expect(failureRecovery(status,false,null,true)).toEqual({outcome:null,error:'denied',rejected:false});
 });
 it('retains an authorized answer during a temporary refresh failure',()=>{
  expect(failureRecovery(503,true,privateAnswer)).toEqual({outcome:privateAnswer,error:'unavailable',rejected:false});
 });
});
