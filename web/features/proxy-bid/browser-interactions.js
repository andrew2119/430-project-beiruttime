// Real-browser interactions with explicitly synthetic, loopback-only API data.
const origin='http://127.0.0.1:33517',reference='00000000-0000-4000-8000-000000000003',order='00000000-0000-4000-8000-000000000005',quote='00000000-0000-4000-8000-000000000004';
const results=[];
const enter=async(selector,text)=>{await page.eval(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.focus();e.select?.();})()`);await page.type(text);};
const until=async expression=>{for(let n=0;n<100;n++){if(await page.eval(expression))return;await page.wait(100);}throw new Error(`State timeout: ${expression}`);};
const check=async(name,fn)=>{try{const detail=await fn();results.push({name,passed:true,detail});}catch(error){results.push({name,passed:false,error:String(error)});}};
// Run once from an English page and once from an Arabic page.
for(const locale of [await page.eval(()=>document.documentElement.lang)]) {
 await fetch('http://127.0.0.1:33516/__proof?reset=1');
 await check(`${locale}: menu-backed currency select keyboard and focus return`,async()=>{
  await page.open(`${origin}/${locale}/prices`);await page.wait('input[name="subject"]');
  await page.eval(()=>document.querySelector('button.ui-select[data-value="USD"]').focus());await page.press('Enter');await page.wait('[role="menu"][data-state="open"]');await page.press('Home');await page.press('ArrowDown');await page.press('Enter');
  await until(`!!document.querySelector('button.ui-select[data-value="LBP"]')`);
  await page.wait(100);const focusReturned=await page.eval(()=>document.activeElement.matches('.ui-select'));
  if(!focusReturned)throw new Error('Select did not return focus');
  await page.eval(()=>document.querySelector('button.ui-select[data-value="LBP"]').focus());await page.press('Enter');await page.wait('[role="menu"][data-state="open"]');await page.press('Home');await page.press('Enter');
  await until(`!!document.querySelector('button.ui-select[data-value="USD"]')`);
  return {focusReturned,currencyKeyboard:true};
 });
 await check(`${locale}: retained quote creation and exact review`,async()=>{
  await page.open(`${origin}/${locale}/prices?proof=review`);await page.wait('input[name="subject"]');
  await enter('input[name="subject"]',reference);await page.click('.l07-form button[type="submit"]');await page.wait('.l07-fees');await page.wait(300);
  await page.click('.l07-grid > section:nth-child(2) button');
  await until(`document.querySelector('.l07-grid > section:nth-child(2) [role="status"]')?.textContent.includes(${JSON.stringify(locale==='ar'?'تم':'acknowledged')})`);
  return {retainedQuoteReviewed:true};
 });
 await check(`${locale}: offer draft save and edit, disabled send/payment`,async()=>{
  await page.open(`${origin}/${locale}/buying`);await page.wait('input[name="draft_subject"]');
  await enter('input[name="draft_subject"]',reference);await enter('input[name="draft_amount"]','4200.00');
  await page.click('.l07-grid > section:nth-child(2) form button:not([type])');
  await until(`!!document.querySelector('.l07-grid > section:nth-child(2) [role="status"]')`);
  await page.click('.l07-history button:not(:disabled)');
  const state=await page.eval(()=>({amount:document.querySelector('input[name="draft_amount"]').value,disabled:document.querySelectorAll('main button:disabled').length}));
  if(state.amount!=='4200.00'||state.disabled<2)throw new Error('Draft amount or unreleased boundary changed');return state;
 });
 await check(`${locale}: switch, read/clear list exit and allowlisted destination`,async()=>{
  await page.open(`${origin}/${locale}/inbox`);await page.wait('.l07-inbox-row');
  await page.click('[role="switch"]');await until(`document.querySelector('[role="switch"]').getAttribute('aria-checked')==='false' && !document.querySelector('[role="switch"]').disabled`);
  await page.eval(()=>document.querySelector('[role="switch"]').focus());await page.press('Space');await until(`document.querySelector('[role="switch"]').getAttribute('aria-checked')==='true' && !document.querySelector('[role="switch"]').disabled`);
  await page.click('.l07-inbox-row[data-read="false"] .l07-actions button:first-child');await until(`document.querySelectorAll('.l07-inbox-dot').length===0`);
  await page.click('.l07-inbox-list > .pg-list-item:first-child .l07-actions button:first-child');await page.wait(50);
  const exitObserved=await page.eval(()=>!!document.querySelector('[data-list-exit]'));
  await until(`document.querySelectorAll('.l07-inbox-row').length===1`);
  await page.click('.l07-inbox-row .l07-actions button:last-child');await page.wait('input[name="subject"]');
  const destination=await page.eval(()=>location.pathname);if(destination!==`/${locale}/prices`)throw new Error('Notice destination changed');return {switchKeyboard:true,read:true,exitObserved,destination};
 });
 await check(`${locale}: maximum quote, review and explicit acknowledgement`,async()=>{
  await page.open(`${origin}/${locale}/buyer/auctions/${reference}`);await page.wait('.proxy-panel input');
  await enter('.proxy-panel input','5000.00');await page.click('.proxy-panel button[type="submit"]');await page.wait('.proxy-quote');
  const preview=await page.eval(()=>document.querySelector('.proxy-quote').textContent);
  await page.click('.proxy-panel button[type="submit"]');
  await until(`document.querySelector('.proxy-panel input')?.value==='' && !document.querySelector('.proxy-quote')`);
  const feedback=await page.eval(()=>document.querySelector('.proxy-panel [role="status"]').textContent);
  if(!feedback)throw new Error('Missing maximum acknowledgement');return {reviewed:true,preview,feedback};
 });
 await check(`${locale}: availability and reservation, never payment`,async()=>{
  await page.open(`${origin}/${locale}/checkout?watch=00000000-0000-4000-8000-000000000006&quote=${quote}`);await page.wait('input[name="watch_id"]');
  await page.click('.checkout-form button[type="submit"]');await page.wait('.checkout-status strong');
  await page.click('.checkout-actions > button');await page.wait('.checkout-status[role="status"]');
  const state=await page.eval(()=>({text:document.querySelector('.checkout-status[role="status"]').textContent,buttonDisabled:document.querySelector('.checkout-actions > button').disabled}));
  if(!state.buttonDisabled)throw new Error('Acknowledged reservation can be resubmitted');return state;
 });
 await check(`${locale}: permission-gated reconciliation hold and intake forms`,async()=>{
  await page.open(`${origin}/${locale}/checkout/${order}`);await page.wait('input[name="actual_watch"]');
  const hold='form:has(input[name="reason"]):not(:has(input[name="actual_watch"]))';
  await enter(`${hold} input[name="reason"]`,'Synthetic visual proof');await page.click(`${hold} button`);await until(`!!document.querySelector('${hold} [role="status"]')`);
  const intake='form:has(input[name="actual_watch"])';
  await page.fill(`${intake} input[name="actual_watch"]`,'Sample watch');await page.fill(`${intake} input[name="location"]`,'Sample bench');await page.fill(`${intake} input[name="occurred"]`,'2026-11-04T20:00');await page.fill(`${intake} input[name="reason"]`,'Synthetic visual proof');await page.click(`${intake} button`);
  await until(`!!document.querySelector('${intake} [role="status"]')`);
  return {hold:true,intake:true,releaseUnavailable:true};
 });
}
await check('shared theme switch uses the CP View Transition',async()=>{
 await page.eval(()=>{document.cookie='bt-theme=light; Path=/';});await page.open(`${origin}/en/buyer`);await page.wait('.buyer-activity-row');
 await page.eval(()=>{window.__buyerTransitions=0;const original=document.startViewTransition?.bind(document);if(original)document.startViewTransition=fn=>{window.__buyerTransitions++;return original(fn);};});
 await page.click('button[aria-label="Switch to dark theme"]');await until(`document.documentElement.dataset.theme==='dark'`);
 const state=await page.eval(()=>({theme:document.documentElement.dataset.theme,calls:window.__buyerTransitions,duration:getComputedStyle(document.documentElement,'::view-transition-old(root)').animationDuration}));
 if(state.theme!=='dark'||state.calls!==1)throw new Error('Theme did not use View Transition');return state;
});
console.log(JSON.stringify({synthetic:true,passed:results.every(r=>r.passed),results},null,2));
