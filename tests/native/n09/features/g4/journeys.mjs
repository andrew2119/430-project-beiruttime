import { check, words, start, fill, button, choose, tick, visible, answer, result, api, ownedOrder, linked, chooseControl } from './browser.mjs';

const local = (ctx, en, ar) => ctx.cell.locale === 'ar' ? ar : en;
function remember(_ctx, value) { return value; }

export async function directory(ctx) {
  const actor = await start(ctx, 'buyer', '/services');
  const t = await words(ctx, 'service-directory');
  const data = await api(ctx, 'service-operations', 'GET', '/v1/directory/businesses?purpose=servicing');
  const profile = data.items.find(item => !item.sample && item.capabilities.length);
  check.ok(profile, 'The directory needs a currently eligible published business');
  await button(ctx, `${t.details}: ${profile.display_name}`);
  await choose(ctx, t.capability, t[profile.capabilities[0]]);
  await button(ctx, t.choose);
  const row = await answer(ctx, '/directory/choices');
  await visible(ctx, t.saved);
  check.equal(row.json.organization_id, profile.organization_id);
  return remember(ctx, { ...result(actor, row), role:'buyer', route:'/services', service:'service-operations',
    read:'/v1/directory/choices/current', id:row.json.id, current:row.json, businessName:profile.display_name,
    privatePath:'/v1/directory/maintenance/' + profile.organization_id });
}

export async function maintenance(ctx) {
  const actor = await start(ctx, 'buyer', '/care/maintenance');
  const order = await ownedOrder(ctx);
  await start(ctx, 'buyer', '/care/maintenance');
  const t = await words(ctx, 'maintenance');
  await fill(ctx, t.watch, order.watch_id);
  await button(ctx, t.open);
  const context = (await answer(ctx, '/maintenance/context/', [200], 'GET')).json;
  const destination = context.destinations.find(item => item.interventions.includes('limited_maintenance'));
  check.ok(destination, 'Current assessment permission and a supported business are required');
  await choose(ctx, t.organization, destination.display_name);
  await fill(ctx, t.symptoms, ctx.uniq('test-timekeeping-observation'));
  await fill(ctx, t.modifications, 'test: modifications unknown; assessment requested');
  await button(ctx, t.limited);
  await tick(ctx, t.permission);
  await tick(ctx, t.safePhoto);
  await button(ctx, t.submitRequest);
  const row = await answer(ctx, '/maintenance/requests');
  check.equal(row.json.state, 'submitted');
  await visible(ctx, t.requestSubmitted);
  const saved = { ...result(actor,row), role:'buyer', route:'/care/maintenance', service:'service-operations',
    watch:order.watch_id, organization:destination.organization_id,
    subject:row.json.request_id,
    read:`/v1/maintenance/operations/${row.json.operation_id}?organization_id=${destination.organization_id}` };
  check.ok(saved.subject, 'Submission must return the service request reference');
  saved.privatePath = saved.read;
  return remember(ctx, saved);
}

export async function appointment(ctx) {
  const source = await maintenance(ctx);
  const route = `/care/appointments?subject=${encodeURIComponent(source.subject)}&organization=${encodeURIComponent(source.organization)}`;
  const actor = await start(ctx, 'buyer', route);
  const t = await words(ctx, 'appointments');
  const date = new Date(Date.now() + 7 * 86400000).toISOString().slice(0,10);
  await fill(ctx, t.date, date);
  await fill(ctx, t.time, '10:30');
  await fill(ctx, t.duration, '30');
  await button(ctx, t.request);
  const row = await answer(ctx, '/appointments/commands');
  check.equal(row.json.state, 'requested');
  check.equal(row.json.custody_received, false);
  await visible(ctx, t.requested);
  return remember(ctx, { ...result(actor,row), role:'buyer', route, service:'service-operations',
    appointment:row.json,
    read:`/v1/appointments/${row.json.appointment_id}?organization_id=${row.json.organization_id}`,
    privatePath:`/v1/appointments/${row.json.appointment_id}?organization_id=${row.json.organization_id}` });
}

export async function intake(ctx) {
  await ctx.actor('buyer');
  const order = await ownedOrder(ctx);
  const actor = await start(ctx, 'dealer', '/business-intake');
  const t = await words(ctx, 'maintenance');
  const organization = await intakeOrganization(ctx, t.organization);
  await fill(ctx, t.order_id, order.id ?? order.order_id);
  await fill(ctx, t.serial, ctx.uniq('test-private-serial'));
  await fill(ctx, t.reference, 'test-watch-reference');
  await fill(ctx, t.movement, 'test-movement-not-inspected');
  await fill(ctx, t.received_condition, 'test: awaiting physical intake; condition unconfirmed');
  await fill(ctx, t.reported_issue, 'test: assessment requested');
  await fill(ctx, t.feeDollars, '0.00');
  await tick(ctx, t.no_polish_acknowledged);
  await button(ctx, t.saveIntake);
  const row = await answer(ctx, '/intake/records');
  check.ok(row.json.id);
  const retained=await api(ctx,'service-operations','GET',`/v1/intake/records/${row.json.id}?organization_id=${organization}`,undefined,'dealer');
  check.equal(retained.state,'awaiting_intake');
  check.equal(retained.diagnosis_allowed,false);
  await visible(ctx, t.saved);
  return remember(ctx, { ...result(actor,row), role:'dealer', route:'/business-intake', service:'service-operations', organization, order:order.id ?? order.order_id,
    read:`/v1/intake/records/${row.json.id}?organization_id=${organization ?? row.json.organization_id}`,
    privatePath:`/v1/intake/records/${row.json.id}?organization_id=${organization ?? row.json.organization_id}` });
}
export async function intakeOrganization(ctx, label) {
  // The business selector exposes only organizations granted to this account.
  let organization = await ctx.page.evaluate(() => {
    const el = document.querySelector('main select');
    return el ? [...el.options].find(option => option.value)?.value : null;
  });
  if (organization) await choose(ctx, label, organization);
  else {
    const selector = await import('./browser.mjs').then(m => m.control(ctx,label));
    await ctx.page.click(selector);
    await ctx.page.waitFor('[role="option"]', {timeout:5000});
    const option = await ctx.page.text('[role="option"]');
    organization = option.trim();
    check.ok(organization, 'The business option must expose its reference');
    await chooseOpen(ctx, option);
  }
  return organization;
}
export async function openIntake(ctx, order, label) {
  await visible(ctx,order);
  const found=await ctx.page.evaluate((order,label)=>{
    const row=[...document.querySelectorAll('main li')].find(el=>el.textContent.includes(order));
    const action=[...(row?.querySelectorAll('button')??[])].find(el=>el.textContent.trim()===label);
    if(!action)return false;
    action.setAttribute('data-g4-open','selected');return true;
  },order,label);
  check.ok(found,'The retained intake must be available in the current queue');
  await ctx.page.click('[data-g4-open="selected"]');
}
async function chooseOpen(ctx, text) {
  const found = await ctx.page.evaluate(text => {
    const el = [...document.querySelectorAll('[role="option"]')].find(el => el.textContent.trim() === text.trim());
    if (!el) return false;
    el.setAttribute('data-g4-option','selected'); return true;
  }, text);
  check.ok(found, 'A currently authorized business must be selectable');
  await ctx.page.click('[data-g4-option="selected"]');
}

export async function cleaning(ctx) {
  const source = await maintenance(ctx);
  const actor = await start(ctx, 'buyer', `/care/cleaning?request=${source.subject}`);
  await ctx.page.waitFor('main textarea', {timeout:8000});
  await fill(ctx, local(ctx,'Current watch condition and known modifications','حالة الساعة الحالية والتعديلات المعروفة'), 'test: visible dust; modifications unknown');
  await fill(ctx, local(ctx,'Preservation limits and areas to avoid','حدود الحفاظ والمناطق التي يجب تجنبها'), 'test: retain original finish; no polishing or opening');
  await tick(ctx, local(ctx,'Case','العلبة'));
  await tick(ctx, local(ctx,'I permit a limited external cleaning assessment. This does not permit opening or work.','أسمح بتقييم محدود للتنظيف الخارجي. هذا لا يسمح بالفتح أو تنفيذ العمل.'));
  await tick(ctx, local(ctx,'I understand that an assembled watch is not assumed safe to submerge.','أفهم أنه لا يُفترض أمان غمر الساعة المجمّعة بالماء.'));
  await tick(ctx, local(ctx,'This request excludes movement service, polishing and opening.','يستثني هذا الطلب صيانة الحركة والتلميع والفتح.'));
  await button(ctx, local(ctx,'Request assessment','طلب التقييم'));
  const row = await answer(ctx, `/cleaning/requests/${source.subject}`);
  check.equal((row.json.record ?? row.json).state, 'requested');
  await visible(ctx, local(ctx,'Assessment requested.','طُلب التقييم.'));
  return remember(ctx, { ...result(actor,row), role:'buyer', route:`/care/cleaning?request=${source.subject}`, service:'service-operations',
    read:`/v1/cleaning/requests/${source.subject}`, privatePath:`/v1/cleaning/requests/${source.subject}` });
}

export async function reduction(ctx) {
  const source = await maintenance(ctx);
  const actor = await start(ctx, 'buyer', '/care/reduction');
  await fill(ctx,local(ctx,'Record reference','مرجع الطلب'),source.subject);
  await fill(ctx,local(ctx,'Business reference','مرجع الجهة'),source.organization);
  await button(ctx,local(ctx,'Open request','فتح الطلب'));
  const context = (await answer(ctx,'/reduction/records/',[200],'GET')).json.context;
  const choice = context.choices.find(item => item.compatible);
  check.ok(choice, 'A current compatible intervention is required');
  await choose(ctx,local(ctx,'Supported intervention','التدخل المدعوم'), local(ctx,
    choice.kind === 'removable_links' ? 'Remove compatible links' : 'Change compatible strap',
    choice.kind === 'removable_links' ? 'نزع وصلات متوافقة' : 'تغيير الحزام المتوافق') + ' · ' + choice.id);
  await fill(ctx,local(ctx,'Target measurement','القياس المستهدف'),'17.5');
  await fill(ctx,local(ctx,'Measurement source','مصدر القياس'),'test: customer measurement');
  await fill(ctx,local(ctx,'Measurement method','طريقة القياس'),'test: circumference tape');
  check.ok(context.authorized_recipient_ids.length);
  await choose(ctx,local(ctx,'Parts recipient','مستلم الأجزاء'),context.authorized_recipient_ids[0]);
  await button(ctx,local(ctx,'Submit request','إرسال الطلب'));
  const row = await answer(ctx,'/commands');
  check.equal(row.json.state,'requested');
  await visible(ctx,local(ctx,'Request saved','تم حفظ الطلب'));
  return remember(ctx,{ ...result(actor,row), role:'buyer',route:'/care/reduction',service:'service-operations',
    read:`/v1/reduction/records/${source.subject}?organization_id=${source.organization}`,
    privatePath:`/v1/reduction/records/${source.subject}?organization_id=${source.organization}` });
}

export async function serviceLifecycle(_ctx, source) {
  check.ok(source.subject, 'The assessment request must have a returned reference');
  // Assessment permission cannot stand in for accepted scope, custody or held job funds.
  // Repair acceptance currently refuses source authorization; no public lifecycle composes it.
  const error = new Error('Connected service lifecycle deferred: current repair acceptance, custody, held job payment and progress source composition are required');
  error.code = 'service_lifecycle_deferred';
  error.operation_id = source.operation_id;
  error.actor_id = source.actor_id;
  throw error;
}

export async function progress(ctx) {
  const source = await maintenance(ctx);
  await serviceLifecycle(ctx, source);
  const actor = await start(ctx,'buyer','/care/progress');
  await ctx.page.fill('#progress-job',source.subject);
  const t = await words(ctx,'care-progress');
  await button(ctx,t.open);
  const row = await answer(ctx,`/progress/${source.subject}`,[200],'GET');
  check.ok(row.json.lines?.length || row.json.items?.length, 'The work log must contain actual accepted lines');
  const report = row.json.items?.find(item=>item.report)?.report;
  check.ok(report, 'An actual work report is required');
  await visible(ctx,ctx.cell.locale === 'ar' ? report.step_ar : report.step_en);
  return remember(ctx,{ ...result(actor,row),role:'buyer',route:'/care/progress',service:'service-operations',
    subject:source.subject,visibleReport:ctx.cell.locale === 'ar' ? report.step_ar : report.step_en,
    read:`/v1/progress/${source.subject}`,privatePath:`/v1/progress/${source.subject}` });
}

export async function quality(ctx) {
  const actor = await start(ctx, 'reviewer', '/business/quality');
  // Each scenario needs independently accepted, completed work and a current
  // work revision. The published page does not create those prerequisites.
  const error = new Error('Connected quality lifecycle deferred: fresh accepted work, completed lines and a current work revision are required for each scenario');
  error.code = 'quality_lifecycle_deferred';
  error.actor_id = actor.actor_id;
  throw error;
}

export async function history(ctx) {
  const source = await maintenance(ctx);
  // A fresh assessment is not released completed work. Keep the connected
  // proof deferred until its own service lifecycle can produce that history.
  return serviceLifecycle(ctx, source);
}

export async function moderation(ctx) {
  const actor = await start(ctx,'buyer','/operations/moderation');
  const t = await words(ctx,'moderation');
  const catalog = await api(ctx,'catalog','GET','/v1/discovery/watches?limit=1');
  const listing = catalog.items[0];
  check.ok(listing?.id, 'A currently public listing is required to report content');
  await fill(ctx,t.targetId,listing.id);
  await fill(ctx,t.evidence,ctx.uniq('test-report-review-request'));
  await button(ctx,t.submitReport);
  const row = await answer(ctx,'/moderation/reports');
  check.ok(row.json.id);
  await visible(ctx,row.json.id);
  return remember(ctx,{ ...result(actor,row),role:'buyer',route:`/operations/moderation?case=${row.json.id}`,service:'trust',
    read:`/v1/moderation/cases/${row.json.id}`,privatePath:`/v1/moderation/cases/${row.json.id}` });
}

export async function signals(ctx) {
  const actor = await start(ctx,'operator','/operations/dashboard');
  const route = '/operations/signals';
  await ctx.page.goto(route);
  await ctx.page.waitFor('#signal-query',{timeout:8000});
  const data = await api(ctx,'trust','GET','/v1/fraud-signals?page=1&page_size=20',undefined,'operator');
  check.ok(data.items.length, 'A real signal operation is required');
  const id = data.items[0].operation_id;
  await ctx.page.fill('#signal-query',id);
  await visible(ctx,id);
  return remember(ctx,{ operation_id:id, actor_id:actor.actor_id,role:'operator',route,service:'trust',
    read:'/v1/fraud-signals?page=1&page_size=20',privatePath:'/v1/fraud-signals?page=1&page_size=20' });
}

export async function passport(ctx) {
  const actor = await start(ctx,'buyer','/watches');
  // The public reader requires an issued reference. Watch details expose no
  // passport destination, and issuance requires a released independent inspection.
  const error = new Error('Connected passport lifecycle deferred: a paid, released independent inspection and its issued passport reference are required; watch details provide no passport destination');
  error.code = 'passport_lifecycle_deferred';
  error.actor_id = actor.actor_id;
  throw error;
}

export async function dashboard(ctx) {
  const actor = await start(ctx,'operator','/operations/dashboard');
  const route = await linked(ctx,'/operations/dashboard/queues/');
  await start(ctx,'operator',route);
  const t = await words(ctx,'moderation');
  await visible(ctx,t.dashboard);
  await button(ctx,t.refresh);
  const row = await answer(ctx,'/operator-workspace/',[200],'GET');
  check.ok(row.json.queues?.length || row.json.items || row.json.id, 'The current queue must be returned');
  return remember(ctx,{ ...result(actor,row),role:'operator',route,service:'communications',
    queueId:route.split('/').pop(),
    read:`/v1/operator-workspace/queues/${route.split('/').pop()}`,privatePath:'/v1/operator-workspace/queues' });
}

export async function language(ctx) {
  const actor = await start(ctx,'buyer','/settings');
  const expected = ctx.cell.locale;
  const other = expected === 'ar' ? 'en' : 'ar';
  const selectLanguage = async locale => {
    await button(ctx,locale === 'ar' ? 'العربية' : 'English');
    await ctx.page.evaluate(async locale => {
      const end=Date.now()+5000;
      while(document.documentElement.lang !== locale) {
        if(Date.now()>end)throw new Error('Language did not change');
        await new Promise(resolve=>setTimeout(resolve,40));
      }
      if(document.documentElement.dir !== (locale==='ar'?'rtl':'ltr'))throw new Error('Wrong reading direction');
    },locale);
  };
  await selectLanguage(other);
  await selectLanguage(expected);
  const id = await ctx.page.evaluate(() => document.querySelector('#settings-language')?.id);
  check.equal(id,'settings-language');
  return remember(ctx,{operation_id:id,actor_id:actor.actor_id,role:'buyer',route:'/settings',local:true});
}

export async function mobile(ctx) {
  const actor = await start(ctx,'buyer','/watches');
  const route = await linked(ctx,'/watches/[^/?]+');
  await ctx.page.goto(route);
  await ctx.page.waitFor('main h1',{timeout:8000});
  const metrics = await ctx.page.evaluate(() => ({width:innerWidth, overflow:document.documentElement.scrollWidth > innerWidth+1,
    heading:document.querySelector('main h1')?.innerText,manifest:document.querySelector('link[rel="manifest"]')?.getAttribute('href')}));
  check.equal(metrics.width,ctx.cell.width);
  check.equal(metrics.overflow,false,'The watch journey must fit the requested viewport');
  check.ok(metrics.heading && metrics.manifest);
  await ctx.page.press('Tab');
  check.equal(await ctx.page.evaluate(() => document.activeElement !== document.body),true);
  const id = route.split('/').pop().split('?')[0];
  return remember(ctx,{operation_id:id,actor_id:actor.actor_id,role:'buyer',route,local:true});
}

export async function help(ctx) {
  const actor = await start(ctx,'buyer','/help');
  const id = await ctx.page.evaluate(() => [...document.querySelectorAll('main bdi')].map(el=>el.textContent).find(text=>/^\d{4}-\d{2}-\d{2}\./.test(text)));
  check.ok(id,'The guidance revision must be visible');
  await ctx.page.fill('#help-search','fees');
  await ctx.page.waitFor('main article',{timeout:5000});
  check.ok(await ctx.page.exists('#help-fees'));
  await ctx.page.fill('#help-search','');
  check.ok(await ctx.page.exists('#help-payments'));
  return remember(ctx,{operation_id:id,actor_id:actor.actor_id,role:'buyer',route:'/help',local:true});
}

export async function finishes(ctx) {
  const source = await cleaning(ctx);
  const subject = new URL(source.route,ctx.origin).searchParams.get('request');
  check.ok(subject, 'The cleaning request must retain its subject');
  const route = `/care/finish?subject=${encodeURIComponent(subject)}`;
  const actor = await start(ctx,'buyer',route);
  await ctx.page.waitFor('main [role="combobox"],main select',{timeout:8000});
  const controls = await ctx.page.evaluate(() => [...document.querySelectorAll('main [role="combobox"],main select')].length);
  check.ok(controls, 'Each assessed finish area needs an explicit choice');
  // No intervention or irreversible finish removal is authorized.
  for(let index=0;index<controls;index++) {
    await ctx.page.evaluate(index=>document.querySelectorAll('main [role="combobox"],main select')[index].setAttribute('data-g4-finish','selected'),index);
    await chooseControl(ctx,'[data-g4-finish="selected"]',local(ctx,'No polishing or brushing','منع الصقل والتشطيب بالفرشاة'));
    await ctx.page.evaluate(()=>document.querySelector('[data-g4-finish]')?.removeAttribute('data-g4-finish'));
  }
  await button(ctx,local(ctx,'Review choices','مراجعة الاختيارات'));
  await button(ctx,local(ctx,'Record these choices','تسجيل هذه الاختيارات'));
  const row=await answer(ctx,'/finish/consents');
  check.equal(row.json.state,'recorded');
  const retained=await api(ctx,'service-operations','GET',`/v1/finish/subjects/${row.json.subject_id}`);
  check.ok(retained.choices.length);
  check.ok(retained.choices.every(item=>item.decision==='no_polish'));
  await visible(ctx,local(ctx,'Your exact choices were recorded.','تم تسجيل اختياراتك الدقيقة.'));
  return remember(ctx,{...result(actor,row),role:'buyer',route,service:'service-operations',
    subject:row.json.subject_id,choices:retained.choices,
    read:`/v1/finish/subjects/${row.json.subject_id}`,privatePath:`/v1/finish/subjects/${row.json.subject_id}`});
}
