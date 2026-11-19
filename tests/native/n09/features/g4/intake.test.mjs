import assert from 'node:assert/strict';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import { intakeOrganization } from './journeys.mjs';

test('intake reads the business reference from the displayed option in both languages', async () => {
  for (const label of ['Represented business', 'المؤسسة التي تمثلها']) {
    const clicks = [];
    const markers = [];
    const option = {textContent:'  test-business-reference  ',setAttribute:(...args)=>markers.push(args)};
    const field = {getClientRects:()=>[{}],getAttribute:name=>name === 'aria-label' ? label : null,
      setAttribute:()=>{}};
    const document = {
      querySelector:()=>null,
      querySelectorAll:selector=>selector === '[role="option"]' ? [option] : [field],
    };
    const ctx = {page:{
      evaluate:async(fn,...args)=>runInNewContext(`(${fn.toString()})(...args)`,{document,args,setTimeout}),
      click:async selector=>clicks.push(selector),
      waitFor:async selector=>assert.equal(selector,'[role="option"]'),
      text:async selector=>{assert.equal(selector,'[role="option"]');return option.textContent;},
    }};
    assert.equal(await intakeOrganization(ctx,label),'test-business-reference');
    assert.deepEqual(clicks,['[data-g4-control="selected"]','[data-g4-option="selected"]']);
    assert.deepEqual(markers,[['data-g4-option','selected']]);
  }
});
