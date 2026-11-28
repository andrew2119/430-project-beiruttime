import {expect,it} from 'vitest';
import {restoreDraft,empty} from './draft';
import {minor} from './api';
it('preserves exact unsaved dollar text and choices without locale conversion',()=>{
 const draft={time_zone:'Asia/Beirut' as const,listing:'watch',opening:'٤٠٠٠٫٢٥',step:'100',bands:[{from:'٥٠٠٠',step:'٢٠٠'}],starts:'2026-11-16T19:00',ends:'2026-11-17T19:00'};
 expect(restoreDraft(JSON.stringify(draft))).toEqual(draft);expect(minor(draft.opening)).toBe(400025);
});
it('never restores private reserve or unknown properties into a stored draft',()=>{
 const restored=restoreDraft(JSON.stringify({...empty,opening:'4000',reserve:'4500',private_file:'bytes',currency:'USD'}));
 expect(restored).toEqual({...empty,opening:'4000'});expect(restored).not.toHaveProperty('reserve');
});
it('does not reinterpret historic non-USD draft amounts as dollars',()=>{
 const restored=restoreDraft(JSON.stringify({...empty,listing:'watch',starts:'date',currency:'LBP',opening:'4000',step:'100',bands:[{from:'5000',step:'200'}]}));
 expect(restored).toEqual({...empty,listing:'watch',starts:'date'});
});
it('does not reinterpret an old UTC draft as Beirut civil time',()=>{
 expect(restoreDraft(JSON.stringify({listing:'watch',opening:'4000',step:'100',starts:'2026-11-16T19:00',ends:'2026-11-17T19:00',currency:'USD'}))).toEqual({...empty,listing:'watch',opening:'4000',step:'100'});
});
it.each([null,'','{','null','[]','42'])('rejects malformed draft %s',saved=>expect(restoreDraft(saved)).toEqual(empty));
