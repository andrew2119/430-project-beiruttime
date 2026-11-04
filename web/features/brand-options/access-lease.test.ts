import { describe, expect, it } from 'vitest';
import { fencePrivateState } from './access-lease';
describe('private state write lease', () => {
  it('fences a delayed response at the access event, before component unmount', async () => {
    const target=new EventTarget(),alive={current:true};let writes=0;
    const close=fencePrivateState(alive,target);
    const delayed=Promise.resolve().then(()=>{if(alive.current)writes++;});
    target.dispatchEvent(new Event('bt:access-change'));
    await delayed;
    expect(alive.current).toBe(false);expect(writes).toBe(0);close();
  });
  it('aborts private readers synchronously on account or organization change', () => {
    const target=new EventTarget(),alive={current:true},abort=new AbortController();
    const close=fencePrivateState(alive,target,()=>abort.abort());
    target.dispatchEvent(new Event('bt:access-change'));
    expect(abort.signal.aborted).toBe(true);expect(alive.current).toBe(false);close();
  });
  it('closes old leases without stopping a newly mounted access context', () => {
    const target=new EventTarget(),first={current:true},second={current:true};
    const closeFirst=fencePrivateState(first,target);closeFirst();
    const closeSecond=fencePrivateState(second,target);
    expect(first.current).toBe(false);expect(second.current).toBe(true);
    closeFirst();expect(second.current).toBe(true);closeSecond();expect(second.current).toBe(false);
  });
});
