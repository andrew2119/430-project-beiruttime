import { describe, it, expect } from 'vitest';
import { formReducer, initialForm, type Form } from '../../../../web/features/authorized-work/form';
describe('private work draft',()=>{
  it('retains mixed-language inputs, selection and exact pending body in place',()=>{
    let state:Form=initialForm;
    for (const [field,value] of Object.entries({...initialForm.fields,job:'job-1',selected:'job-1',note:'ملاحظة طويلة Latin 🔧',part:'جزء A',before:'12',after:'-2',beforeAt:'2026-11-17T12:30:00Z',afterAt:'2026-11-17T13:05:00Z',nextAction:'مراجعة',nextActor:'person'})) {
      state=formReducer(state,{type:'field',field:field as keyof typeof initialForm.fields,value});
    }
    const before=state;
    state=formReducer(state,{type:'language'});
    expect(state).toBe(before);
    state=formReducer(state,{type:'prepare',attempt:{operation:'stable-reference',body:JSON.stringify(state.fields)}});
    const pending=state;
    state=formReducer(state,{type:'language'});
    expect(state).toBe(pending);
    state=formReducer(state,{type:'field',field:'note',value:'replacement'});
    expect(state).toBe(pending);
    state=formReducer(state,{type:'prepare',attempt:{operation:'duplicate',body:'different'}});
    expect(state).toBe(pending);
    state=formReducer(state,{type:'acknowledged',operation:'other'});
    expect(state).toBe(pending);
    state=formReducer(state,{type:'acknowledged',operation:'stable-reference'});
    expect(state.attempt).toBeNull();
    expect(state.fields).toEqual(before.fields);
  });
  it('starts a fresh private partition with no previous draft',()=>{
    expect(initialForm.attempt).toBeNull();
    expect(initialForm.fields.note).toBe('');
  });
});
