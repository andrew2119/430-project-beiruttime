import { check, start, fill, button, visible, denied, api, words } from './browser.mjs';
import * as paths from './journeys.mjs';
import { retainedPage } from './recovery.mjs';

function proof(value) {
  check.ok(typeof value.operation_id === 'string' && value.operation_id.length);
  check.ok(typeof value.actor_id === 'string' && value.actor_id.length);
  return {operation_id:value.operation_id,actor_id:value.actor_id};
}

async function invalidSearchReference(ctx) {
  const address = await ctx.page.url();
  const url = new URL(address, ctx.origin);
  check.equal(url.pathname, `/${ctx.cell.locale}/watches`);
  check.equal(url.searchParams.get('min_price'), '20');
  check.equal(url.searchParams.get('max_price'), '10');
  return address;
}

async function languageNegative(ctx) {
  const actor = await start(ctx,'buyer','/watches?min_price=20&max_price=10');
  const other = ctx.cell.locale === 'ar' ? 'en' : 'ar';
  for (const locale of [ctx.cell.locale, other, ctx.cell.locale]) {
    if (await ctx.page.evaluate(() => document.documentElement.lang) !== locale) {
      await button(ctx,locale === 'ar' ? 'العربية' : 'English');
    }
    const t = await words({cell:{locale}},'discovery');
    await visible(ctx,t.rangeError);
    const state = await ctx.page.evaluate(() => ({lang:document.documentElement.lang,dir:document.documentElement.dir}));
    check.equal(state.lang,locale);
    check.equal(state.dir,locale === 'ar' ? 'rtl' : 'ltr');
    check.equal(await ctx.page.exists('main a[href*="/watches/"]'),false,'Changing language cannot bypass range validation');
  }
  return {operation_id:await invalidSearchReference(ctx),actor_id:actor.actor_id};
}

async function helpNegative(ctx) {
  const saved = await paths.help(ctx);
  const query = ctx.uniq('test-no-matching-guidance');
  await ctx.page.fill('#help-search',query);
  await visible(ctx,ctx.cell.locale === 'ar' ? 'لا توجد إرشادات مطابقة' : 'No matching guidance');
  check.equal(await ctx.page.exists('main article'),false,'Unmatched guidance must not show unrelated results');
  check.ok(await ctx.page.exists(`a[href="/${ctx.cell.locale}/account?next=%2Fhelp"]`),'Access recovery stays available');
  await visible(ctx,saved.operation_id);
  return saved;
}

async function mobileNegative(ctx) {
  const actor = await start(ctx,'buyer','/watches?min_price=20&max_price=10');
  const t = await words(ctx,'discovery');
  check.ok(t.rangeError,'The price validation message must be published');
  await visible(ctx,t.rangeError);
  check.equal(await ctx.page.exists('main a[href*="/watches/"]'),false,'Invalid ranges cannot display successful search results');
  return {operation_id:await invalidSearchReference(ctx),actor_id:actor.actor_id};
}

function identity(value) {
  const record = value.choice ?? value.record ?? value.result ?? value;
  const fields = ['id','operation_id','appointment_id','subject_id','watch_id','organization_id','revision','state','capability','purpose','choices','items','queues','summary'];
  const selected = Object.fromEntries(fields.filter(key => record?.[key] !== undefined).map(key=>[key,record[key]]));
  check.ok(Object.keys(selected).length,'A recovery read needs a returned record identity');
  return selected;
}

async function recover(ctx, journey) {
  const saved = await journey(ctx);
  if (saved.local) {
    await ctx.page.reload();
    await ctx.page.waitFor('main h1',{timeout:8000});
    if(saved.route === '/settings') {
      const locale = await ctx.page.evaluate(()=>({lang:document.documentElement.lang,dir:document.documentElement.dir,
        theme:document.documentElement.getAttribute('data-theme')}));
      check.equal(locale.lang,ctx.cell.locale);
      check.equal(locale.dir,ctx.cell.locale === 'ar' ? 'rtl' : 'ltr');
      check.equal(locale.theme,ctx.cell.theme);
      check.equal(await ctx.page.evaluate(()=>document.querySelector('#settings-language')?.id),saved.operation_id);
    } else if(saved.route === '/help') {
      await visible(ctx,saved.operation_id);
      await ctx.page.fill('#help-search','fees');
      check.ok(await ctx.page.exists('main article'),'Guidance remains searchable after reload');
    } else {
      check.ok((await ctx.page.url()).includes(saved.operation_id));
      check.ok((await ctx.page.text('main h1')).trim());
    }
    return proof(saved);
  }
  const before = await api(ctx,saved.service,'GET',saved.read,undefined,saved.role);
  await ctx.page.reload();
  await ctx.page.waitFor('main h1',{timeout:8000});
  const after = await api(ctx,saved.service,'GET',saved.read,undefined,saved.role);
  check.deepEqual(identity(after),identity(before),'Reload must retain the acknowledged record without another mutation');
  if (await retainedPage(ctx, saved, after)) return proof(saved);
  if(saved.route === '/care/progress') {
    const t=await words(ctx,'care-progress');
    await ctx.page.fill('#progress-job',saved.subject);
    await button(ctx,t.open);
    await visible(ctx,saved.visibleReport);
  } else if(saved.route === '/care/history') {
    const t=await words(ctx,'service-history');
    await fill(ctx,t.watch,saved.watch);
    await fill(ctx,t.revision,saved.watchRevision);
    await button(ctx,t.open);
    await visible(ctx,saved.visibleRecord);
  } else if(saved.route === '/business-intake') {
    const t=await words(ctx,'maintenance');
    const {choose}=await import('./browser.mjs');
    await choose(ctx,t.organization,saved.organization);
    for(let offset=0;offset<(saved.offset ?? 0);offset+=50)await button(ctx,t.nextPage);
    await paths.openIntake(ctx,saved.order,t.open);
    await visible(ctx,t.diagnosisNotAllowed);
  } else if(saved.public) await ctx.page.waitFor('main dl',{timeout:8000});
  else if(saved.route.includes('moderation?case=')) await visible(ctx,after.id);
  else if(saved.route.includes('cleaning?request=')) {
    await visible(ctx,ctx.cell.locale === 'ar' ? 'طُلب التقييم.' : 'Assessment requested.');
  } else if(saved.route === '/care/maintenance') {
    const t=await words(ctx,'maintenance');
    await fill(ctx,t.watch,saved.watch);
    await button(ctx,t.open);
    await ctx.page.waitFor('main textarea',{timeout:8000});
  } else if(saved.route === '/care/reduction') {
    const record=after.record;
    check.ok(record);
    await fill(ctx,ctx.cell.locale === 'ar'?'مرجع الطلب':'Record reference',record.subject_id);
    await fill(ctx,ctx.cell.locale === 'ar'?'مرجع الجهة':'Business reference',record.organization_id);
    await button(ctx,ctx.cell.locale === 'ar'?'فتح الطلب':'Open request');
    await visible(ctx,ctx.cell.locale === 'ar'?'تم حفظ الطلب':'Request saved');
  }
  return proof(saved);
}

function feature(number, journey, negative) {
  return {
    feature_id:`F${number}`,proof_id:`f${number}-proof`,proof_revision:'1',
    journey:async ctx=>proof(await journey(ctx)),
    negative:async ctx=>proof(await (negative ? negative(ctx) : (async()=>{
      const saved=await journey(ctx);
      return denied(ctx,saved.service,saved.privatePath);
    })())),
    recovery:async ctx=>recover(ctx,journey),
  };
}

export const features = [
  feature(49,paths.directory),
  feature(50,paths.appointment),
  feature(51,paths.intake),
  feature(52,paths.maintenance),
  feature(53,paths.finishes),
  feature(54,paths.reduction),
  feature(55,paths.progress),
  feature(56,paths.quality),
  feature(57,paths.history),
  feature(58,paths.moderation),
  feature(59,paths.signals),
  feature(60,paths.passport,async ctx=>{
    const saved=await paths.passport(ctx);
    return denied(ctx,saved.service,saved.privatePath,'buyer');
  }),
  feature(61,paths.dashboard),
  feature(62,paths.language,languageNegative),
  feature(63,paths.mobile,mobileNegative),
  feature(64,paths.help,helpNegative),
];
