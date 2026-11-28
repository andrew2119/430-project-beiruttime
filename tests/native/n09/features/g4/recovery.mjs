import { check, words, visible, button } from './browser.mjs';

export async function retainedPage(ctx, saved, retained) {
  if (saved.route === '/services') {
    const t = await words(ctx, 'service-directory');
    const choice = retained.choice;
    check.equal(choice.id, saved.id);
    check.equal(choice.organization_id, saved.current.organization_id);
    check.equal(choice.capability, saved.current.capability);
    await visible(ctx, `${t.restored} · ${t[choice.capability]}`);
    await visible(ctx, saved.businessName);
    return true;
  }
  if (saved.route.startsWith('/care/appointments?')) {
    check.equal(retained.appointment_id, saved.appointment.appointment_id);
    check.equal(retained.state, saved.appointment.state);
    check.equal(retained.instant, saved.appointment.instant);
    const route = new URL(saved.route, ctx.origin);
    route.searchParams.set('appointment', retained.appointment_id);
    await ctx.page.goto(route.pathname + route.search);
    const t = await words(ctx, 'appointments');
    await visible(ctx, retained.instant);
    await visible(ctx, t[retained.state]);
    await visible(ctx, t[retained.purpose]);
    return true;
  }
  if (saved.route.startsWith('/care/finish?')) {
    check.equal(retained.source.subject_id, saved.subject);
    check.deepEqual(retained.choices, saved.choices);
    await visible(ctx, ctx.cell.locale === 'ar' ? 'تم تسجيل اختياراتك الدقيقة.' : 'Your exact choices were recorded.');
    for (const area of retained.source.areas) {
      await visible(ctx, ctx.cell.locale === 'ar' ? area.name_ar : area.name_en);
    }
    const choices = await ctx.page.evaluate(() => [...document.querySelectorAll('main select,main [role="combobox"]')].map(el =>
      el.tagName === 'SELECT' ? el.value : el.textContent.trim()));
    check.equal(choices.length, retained.choices.length);
    const label = ctx.cell.locale === 'ar' ? 'منع الصقل والتشطيب بالفرشاة' : 'No polishing or brushing';
    check.ok(choices.every(value => value === 'no_polish' || value === label), 'Reload must display every retained finish choice');
    return true;
  }
  if (saved.route === '/operations/signals') {
    const item = retained.items.find(item => item.operation_id === saved.operation_id);
    check.ok(item, 'The acknowledged signal must remain in the current read');
    await ctx.page.fill('#signal-query', saved.operation_id);
    await visible(ctx, saved.operation_id);
    const state = ctx.cell.locale === 'ar'
      ? (item.state === 'review_required' ? 'مراجعة يدوية مطلوبة' : 'لا توجد إشارة مرصودة')
      : (item.state === 'review_required' ? 'Manual review required' : 'No observable signal');
    await visible(ctx, state);
    return true;
  }
  if (saved.route.includes('/operations/dashboard/queues/')) {
    const t = await words(ctx, 'moderation');
    const queue = retained.queues ? retained.queues.find(item => item.id === saved.queueId) : retained;
    check.equal(queue?.id, saved.queueId);
    await button(ctx, t.refresh);
    await visible(ctx, t[queue.id] ?? t.unknownState);
    await visible(ctx, t[queue.state] ?? t.unknownState);
    for (const item of queue.items) {
      await visible(ctx, item.id);
      await visible(ctx, t[item.status] ?? t.unknownState);
    }
    return true;
  }
  return false;
}
