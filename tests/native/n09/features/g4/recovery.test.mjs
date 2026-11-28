import assert from 'node:assert/strict';
import test from 'node:test';
import { retainedPage } from './recovery.mjs';
import { words } from './browser.mjs';

function context(locale, text, choices = []) {
  const calls = [];
  return {cell:{locale},origin:'http://localhost:3000',calls,page:{
    goto:async route=>calls.push(['goto',route]),
    fill:async (...args)=>calls.push(['fill',...args]),
    click:async ()=>{},
    evaluate:async (fn, value)=>{
      if (fn.toString().includes('innerText.includes')) {
        assert.ok(text.includes(value), `Missing visible result: ${value}`);
      } else if (fn.toString().includes('combobox')) return choices;
      else return true;
    },
  }};
}

test('retained pages require visible identity and state after reload in each language', async()=>{
  for (const locale of ['en','ar']) {
    const directory = await words({cell:{locale}},'service-directory');
    const appointments = await words({cell:{locale}},'appointments');
    const moderation = await words({cell:{locale}},'moderation');
    const choice={id:'test-choice',organization_id:'test-business',capability:'servicing'};
    const visit={appointment_id:'test-visit',state:'requested',instant:'2030-01-02T10:30:00Z',purpose:'assessment'};
    const source={subject_id:'test-subject',areas:[{name_en:'test-case',name_ar:'test-case'}]};
    const choices=[{area_id:'test-area',decision:'no_polish'}];
    const queue={id:'test-queue',state:'empty',items:[]};
    const cases=[
      [{route:'/services',id:choice.id,current:choice,businessName:'test-business-name'}, {choice},
        [`${directory.restored} · ${directory.servicing}`,'test-business-name']],
      [{route:'/care/appointments?subject=test-subject',appointment:visit},visit,
        [visit.instant,appointments.requested,appointments.assessment]],
      [{route:'/care/finish?subject=test-subject',subject:source.subject_id,choices},{source,choices},
        [locale==='ar'?'تم تسجيل اختياراتك الدقيقة.':'Your exact choices were recorded.','test-case']],
      [{route:'/operations/signals',operation_id:'test-signal'}, {items:[{operation_id:'test-signal',state:'review_required'}]},
        ['test-signal',locale==='ar'?'مراجعة يدوية مطلوبة':'Manual review required']],
      [{route:'/operations/dashboard/queues/test-queue',queueId:queue.id},queue,
        [moderation.unknownState,moderation.empty]],
    ];
    for (const [saved,retained,text] of cases) {
      const ctx=context(locale,text,['no_polish']);
      assert.equal(await retainedPage(ctx,saved,retained),true);
      for (const missing of text) {
        await assert.rejects(retainedPage(context(locale,text.filter(value=>value!==missing),['no_polish']),saved,retained),/Missing visible result/);
      }
      if(saved.appointment) assert.ok(ctx.calls[0][1].includes('appointment=test-visit'));
      if(saved.operation_id) assert.deepEqual(ctx.calls[0],['fill','#signal-query','test-signal']);
    }
    await assert.rejects(retainedPage(context(locale,[locale==='ar'?'تم تسجيل اختياراتك الدقيقة.':'Your exact choices were recorded.','test-case'],['consent']),cases[2][0],cases[2][1]),/retained finish choice/);
  }
});
