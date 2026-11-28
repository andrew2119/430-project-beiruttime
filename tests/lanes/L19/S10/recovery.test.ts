import { describe, expect, it } from 'vitest';
import { submitWithRecovery } from '../../../../web/features/authorized-work/recovery';
import { formReducer, initialForm } from '../../../../web/features/authorized-work/form';

describe('uncertain observation recovery',()=>{
  it('unlocks the retained draft after a lost response and changed source revision',async()=>{
    const attempt={operation:'test-operation',body:'{"source_revision":1}'};
    let state=formReducer(initialForm,{type:'prepare',attempt});
    let recorded=false;
    const sent:string[]=[];
    const send=async(retained:typeof attempt)=>{
      sent.push(retained.body);
      if (!recorded) { recorded=true; throw new Error('Lost response'); }
      throw new Error('Stale source revision');
    };
    const receipt={operation_id:attempt.operation,state:'recorded' as const};
    await expect(submitWithRecovery(attempt,send,async()=>{throw new Error('Unavailable');},()=>false)).rejects.toThrow('Lost response');
    expect(state.attempt).toEqual(attempt);
    const answer=await submitWithRecovery(state.attempt!,send,async operation=>{
      expect(operation).toBe(attempt.operation);
      return receipt;
    },()=>false);
    state=formReducer(state,{type:'acknowledged',operation:answer.operation_id});
    expect(state.attempt).toBeNull();
    state=formReducer(state,{type:'field',field:'note',value:'Next observation'});
    expect(state.fields.note).toBe('Next observation');
    expect(sent).toEqual([attempt.body,attempt.body]);
  });
  it('allows the identical retry when a timed out command has no receipt',async()=>{
    const attempt={operation:'test-operation',body:'test-body'};
    let calls=0;
    const send=async(retained:typeof attempt)=>{
      expect(retained).toBe(attempt);
      if (++calls===1) throw new Error('Timeout');
      return {operation_id:attempt.operation,state:'recorded' as const};
    };
    await expect(submitWithRecovery(attempt,send,async()=>{throw new Error('Absent receipt');},()=>false)).rejects.toThrow('Timeout');
    expect((await submitWithRecovery(attempt,send,async()=>{throw new Error('Absent receipt');},()=>false)).state).toBe('recorded');
  });
  it('retains pending results and never looks up a definitive rejection',async()=>{
    const attempt={operation:'test-operation',body:'test-body'};
    const pending=await submitWithRecovery(attempt,async()=>{throw new Error('Timeout');},async()=>({operation_id:attempt.operation,state:'pending' as const}),()=>false);
    expect(pending.state).toBe('pending');
    let lookedUp=false;
    await expect(submitWithRecovery(attempt,async()=>{throw new Error('Denied');},async()=>{lookedUp=true;return pending;},()=>true)).rejects.toThrow('Denied');
    expect(lookedUp).toBe(false);
  });
  it('unlocks definitively rejected paused work so another incident can be prepared',async()=>{
    const attempt={operation:'test-paused-progress',body:'test-progress-body'};
    let state=formReducer(initialForm,{type:'prepare',attempt});
    const rejection={code:'paused',not_applied:true};
    let lookedUp=false;
    try {
      await submitWithRecovery(attempt,async()=>{throw rejection;},async()=>{
        lookedUp=true;
        throw new Error('No receipt');
      },error=>error===rejection && rejection.not_applied);
    } catch (error) {
      expect(error).toBe(rejection);
      state=formReducer(state,{type:'acknowledged',operation:attempt.operation});
    }
    expect(lookedUp).toBe(false);
    expect(state.attempt).toBeNull();
    state=formReducer(state,{type:'field',field:'kind',value:'loss'});
    state=formReducer(state,{type:'prepare',attempt:{operation:'test-new-incident',body:'test-loss-body'}});
    expect(state.fields.kind).toBe('loss');
    expect(state.attempt?.operation).toBe('test-new-incident');
  });

});
