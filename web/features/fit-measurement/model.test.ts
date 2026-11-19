import { describe, expect, it } from 'vitest';
import { createReadFence, millimeters, refreshedStatus } from './model';
describe('exact circumference',()=>{
  it.each([['17.5cm','cm',175],['١٧٫٥ سم','cm',175],['۱۷٫۵ سم','cm',175],['80','mm',80],['300','mm',300]] as const)('%s means exact millimeters',(raw,unit,expected)=>expect(millimeters(raw,unit)).toBe(expected));
  it.each(['17,5','1,750','١٧٬٥','17.50','17٫.5','1e2','+175','NaN','∞','','7.9','30.1','17.5 mm'])('rejects %s',raw=>expect(millimeters(raw,'cm')).toBeNull());
  it.each(['79','301','175.5'])('rejects %s millimeters',raw=>expect(millimeters(raw,'mm')).toBeNull());
});

describe('context refresh during an uncertain command',()=>{
  it('retains pending through failure and recovery until the command resolves',()=>{
    const failed=refreshedStatus('pending','unavailable');
    expect(failed).toBe('pending');
    expect(refreshedStatus(failed,'verified')).toBe('pending');
  });
  it('keeps an in-flight save protected during refresh',()=>{
    expect(refreshedStatus('saving','unavailable')).toBe('saving');
    expect(refreshedStatus('saving','verified')).toBe('saving');
  });
  it('lets current denial override pending and prevents a late read reopening access',()=>{
    expect(refreshedStatus('pending','denied')).toBe('denied');
    expect(refreshedStatus('saving','denied')).toBe('denied');
    expect(refreshedStatus('denied','verified')).toBe('denied');
  });
  it('requires a verified reload for an ordinary unavailable record',()=>{
    expect(refreshedStatus('ready','unavailable')).toBe('unavailable');
    expect(refreshedStatus('unavailable','verified')).toBe('ready');
    expect(refreshedStatus('stale','verified')).toBe('ready');
  });
});

it('discards an earlier context answer after a save denial and keeps revocation across refreshes',async()=>{
  const fence=createReadFence();
  let finish!:(value:{circumference_mm:number})=>void;
  const earlierRead=new Promise<{circumference_mm:number}>(resolve=>{finish=resolve;});
  let displayed:{circumference_mm:number}|null={circumference_mm:175};
  const receive=earlierRead.then(answer=>{if(fence.accepts()) displayed=answer;});
  fence.revoke();
  displayed=null;
  finish({circumference_mm:175});
  await receive;
  expect(displayed).toBeNull();
  expect(fence.accepts()).toBe(false);
  expect(createReadFence().accepts()).toBe(true);
});
