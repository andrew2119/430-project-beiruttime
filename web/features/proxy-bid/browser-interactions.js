// Real-browser interactions with explicitly synthetic, loopback-only API data.
const auctionListing='00000000-0000-4000-8000-000000000003';
const origin='http://127.0.0.1:33517',reference='00000000-0000-4000-8000-000000000014',order='00000000-0000-4000-8000-000000000005';
const checkoutQuote='00000000-0000-4000-8000-000000000021';
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
  await page.click('.l07-inbox-list .l07-inbox-row .l07-actions button:first-child');await page.wait(50);
  const exitObserved=await page.eval(()=>!!document.querySelector('[data-list-exit]'));
  await until(`document.querySelectorAll('.l07-inbox-row').length===1`);
  await page.click('.l07-inbox-row .l07-actions button:last-child');await page.wait('input[name="subject"]');
  const destination=await page.eval(()=>location.pathname);if(destination!==`/${locale}/prices`)throw new Error('Notice destination changed');return {switchKeyboard:true,read:true,exitObserved,destination};
 });
 await check(`${locale}: maximum quote, review and explicit acknowledgement`,async()=>{
  const fixture='http://127.0.0.1:33516';
  await fetch(fixture+'/__proof?reset=1');
  const auction='/v1/auctions/00000000-0000-4000-8000-000000000008';
  const initial=await (await fetch(fixture+auction+'/history')).json();
  if(initial.items.length!==0||initial.snapshot.accepted_sequence!==0||initial.snapshot.leader!==null)
    throw new Error('Competition must start with an empty auction');
  async function placeIncumbentStep(path,body) {
    const response=await fetch(fixture+path,{method:'POST',headers:{'Content-Type':'application/json',
      Authorization:'Bearer synthetic-incumbent-token','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(body)});
    if(!response.ok)throw new Error('Simulated incumbent request failed');
    return response.json();
  }
  const previewRequest={subject_id:initial.snapshot.id,subject_revision:initial.snapshot.revision,purpose:'bid',
    currency:'USD',price_minor:initial.snapshot.opening_minor,schedule_id:'usd-v2',source:'sample'};
  const feePreview=await placeIncumbentStep('/v1/quotes',previewRequest);
  await placeIncumbentStep('/v1/quotes/'+feePreview.id+'/review',
    {...previewRequest,quote_revision:feePreview.revision,payable_minor:feePreview.payable_minor});
  const incumbent=await placeIncumbentStep(auction+'/bids',{amount_minor:previewRequest.price_minor,
    fee_quote_id:feePreview.id,expected_revision:initial.snapshot.revision});
  const before=await (await fetch(fixture+auction+'/history')).json();
  if(incumbent.status!=='succeeded'||before.items.length!==1||before.items[0].automatic||
    before.items[0].bidder!==before.snapshot.leader||before.snapshot.revision!==incumbent.revision)
    throw new Error('Simulated opening bid did not set the incumbent');
  const buyerHeaders={'Content-Type':'application/json',Authorization:'Bearer synthetic-visual-proof-only'};
  const unreviewed=await fetch(fixture+'/v1/quotes',{method:'POST',
    headers:{...buyerHeaders,'Idempotency-Key':crypto.randomUUID()},
    body:JSON.stringify({...previewRequest,subject_revision:before.snapshot.revision,price_minor:500000})});
  if(!unreviewed.ok)throw new Error('Could not create the simulated buyer preview');
  const unreviewedQuote=await unreviewed.json();
  const invalidReview=await fetch(fixture+'/v1/quotes/'+unreviewedQuote.id+'/review',{method:'POST',
    headers:{...buyerHeaders,'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({price_minor:1})});
  if(invalidReview.status!==422)throw new Error('The incomplete fee review was accepted');
  const wrongPrice=await fetch(fixture+'/v1/quotes/'+unreviewedQuote.id+'/review',{method:'POST',
    headers:{...buyerHeaders,'Idempotency-Key':crypto.randomUUID()},
    body:JSON.stringify({...previewRequest,subject_revision:before.snapshot.revision,price_minor:500001,
      quote_revision:unreviewedQuote.revision,payable_minor:unreviewedQuote.payable_minor})});
  if(wrongPrice.status!==409)throw new Error('The wrong fee review amount was accepted');
  await page.open(`${origin}/${locale}/buyer/auctions/${auctionListing}`);
  await page.wait('.proxy-panel > form input:not(:disabled)');
  await enter('.proxy-panel > form input','5000.00');await page.click('.proxy-panel > form button[type="submit"]');await page.wait('.proxy-quote');
  const preview=await page.eval(()=>document.querySelector('.proxy-quote').textContent);
  await page.click('.proxy-panel > form button[type="submit"]');
  await until(`document.querySelector('.proxy-panel > form input')?.value==='' && !document.querySelector('.proxy-quote')`);
  const feedback=await page.eval(()=>document.querySelector('.proxy-panel [role="status"]').textContent);
  if(!feedback)throw new Error('Missing maximum acknowledgement');
  const {snapshot,items}=await (await fetch(fixture+auction+'/history')).json();
  const challenge=items.at(-1);
  if(items.length!==before.items.length+1||challenge.amount_minor!==before.snapshot.next_minimum_minor||
    snapshot.current_minor!==challenge.amount_minor||snapshot.leader!==challenge.bidder||
    snapshot.leader===before.snapshot.leader||!challenge.automatic||
    snapshot.accepted_sequence!==challenge.sequence) throw new Error('Maximum acknowledgement did not advance public competition');
  const ceiling=async token=>{
    const response=await fetch(fixture+auction+'/maximum',{method:'POST',
      headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},
      body:JSON.stringify({action:'read_v2'})});
    if(!response.ok)throw new Error('Could not check the simulated buyer scope');
    return response.json();
  };
  const own=await ceiling('synthetic-visual-proof-only');
  const other=await ceiling('synthetic-incumbent-token');
  if(own.amount_minor!==500000||other.amount_minor!==null||other.active||other.actor_id===own.actor_id)
    throw new Error('The private ceiling escaped its buyer scope');
  return {reviewed:true,preview,feedback};
 });
 await check(`${locale}: language control preserves the mounted maximum and pending reference`,async()=>{
  const fixture='http://127.0.0.1:33516/__proof';
  await fetch(fixture+'?reset=1&mode=pending-maximum');
  const other=locale==='en'?'ar':'en';
  const input='.proxy-panel > form input';
  const submit='.proxy-panel > form button[type="submit"]';
  const change=async language=>{
    await page.click(`[role="radio"]:has(span[lang="${language}"])`);
    const brand=language==='ar'?'بيروت تايم':'Beirut Time';
    const skip=language==='ar'?'انتقل إلى المحتوى':'Skip to content';
    await until(`document.documentElement.lang==='${language}' && document.documentElement.dir==='${language==='ar'?'rtl':'ltr'}' &&
      [...document.querySelectorAll('a[href="#main-content"]')].some(link=>link.textContent.trim()===${JSON.stringify(skip)}) &&
      [...document.querySelectorAll('aside, header')].some(region=>
        [...region.querySelectorAll('a[href="/${language}"]')].some(link=>link.textContent.trim()===${JSON.stringify(brand)}))`);
    const same=await page.eval(`document.querySelector('${input}')===window.originalMaximumInput &&
      window.originalMaximumInput.value==='5000.00' &&
      location.search==='?auction=00000000-0000-4000-8000-000000000008&view=leading' &&
      location.hash==='#maximum'`);
    if(!same) throw new Error('Language change replaced the input or its route state');
  };
  try {
    await page.open(`${origin}/${locale}/buyer/auctions/${auctionListing}?auction=00000000-0000-4000-8000-000000000008&view=leading#maximum`);
    await page.wait(input+':not(:disabled)');
    await enter(input,'5000.00');
    await page.eval(`window.originalMaximumInput=document.querySelector('${input}')`);
    await change(other);
    await page.click(submit);
    await page.wait('.proxy-quote');
    const simulated=await page.eval(()=>document.querySelector('.proxy-quote').textContent);
    if(!simulated.includes(other==='ar'?'معاينة رسوم محاكاة':'Simulated fee preview')) throw new Error('Missing simulated fee disclosure');
    await change(locale);
    await page.click(submit);
    const label=locale==='ar'?'مرجع الطلب':'Request reference';
    await until(`[...document.querySelectorAll('.proxy-panel div[role="status"] p')].some(row=>row.textContent.startsWith(${JSON.stringify(label)}))`);
    const operation=await page.eval(()=>document.querySelector('.proxy-panel div[role="status"] bdi').textContent);
    for(const language of [other,locale]) {
      await change(language);
      const current=await page.eval(()=>document.querySelector('.proxy-panel div[role="status"] bdi')?.textContent);
      if(current!==operation) throw new Error('Language change replaced the original bid reference');
    }
    if((await (await fetch(fixture)).json()).maximumPosts!==1) throw new Error('Language change resubmitted the bid');
    return {sameInput:true,sameReference:true};
  } finally {
    await fetch(fixture+'?reset=1');
  }
 });
 for(const scenario of ['support-committed','support-not-delivered','support-active-history']) await check(`${locale}: support history recovery ${scenario}`,async()=>{
  const fixture='http://127.0.0.1:33516/__proof';
  const won=`${origin}/${locale}/buyer?view=won`;
  const contact='a[href*="/support?auction="]:not([href*="view=history"])';
  const history='a[href*="/support?auction="][href*="view=history"]';
  const proofHeaders={Authorization:'Bearer synthetic-visual-proof-only'};
  const service='http://127.0.0.1:33516';
  const checkBinding=async(expectedHold)=>{
    const read=async(path)=>(await fetch(service+path,{headers:proofHeaders})).json();
    const [result]=(await read('/v1/buyer-workspace?view=won')).items;
    const conversation=await read(`/v1/support/auction-results/${result.auction_id}`);
    const {order:boundOrder,history:orderHistory}=await read(`/v1/orders/${result.order_id}`);
    const auction=await read(`/v2/auctions/${result.auction_id}`);
    const active=expectedHold==='active';
    const attemptAt=Date.parse(orderHistory?.[2]?.occurred_at);
    const confirmationAt=active?null:Date.parse(orderHistory?.at(-1)?.occurred_at);
    const noticeAt=Date.parse(boundOrder?.notified_at),baseDeadline=noticeAt+24*60*60*1000;
    const extendedDeadline=baseDeadline+24*60*60*1000;
    const expectedHistory=['allocate','payment-notified','payment-attempt',...(active?[]:['payment-confirmed'])];
    if(!boundOrder||!Array.isArray(orderHistory)||!result.order_id||conversation.order_id!==result.order_id||boundOrder.id!==result.order_id||
      result.auction_id!==conversation.auction_id||auction.id!==result.auction_id||result.listing_id!==auction.listing_id||
      result.watch_id!==boundOrder.watch_id||result.listing_id!==boundOrder.listing_id||conversation.buyer_id!==boundOrder.buyer_id||
      auction.status!=='ended'||auction.mode!=='closed_winner'||auction.ends_at!==auction.scheduled_ends_at||result.ended_at!==auction.ends_at||
      !(Date.parse(auction.starts_at)<Date.parse(auction.ends_at)&&Date.parse(auction.ends_at)<=Date.parse(auction.server_time))||
      result.final_minor!==auction.current_minor||result.financial_state!==(active?'unknown':'paid_held')||
      boundOrder.state!==(active?'payment_unknown':'paid_held')||conversation.hold_state!==expectedHold||
      boundOrder.payment_method!=='card'||boundOrder.notification_state!=='notified'||
      !Number.isFinite(noticeAt)||Date.parse(boundOrder.initiation_extended_until)!==extendedDeadline||Date.parse(boundOrder.deadline)!==extendedDeadline||
      orderHistory.map(entry=>entry.action).join(',')!==expectedHistory.join(',')||
      orderHistory.some((entry,index)=>entry.revision!==index+1||!(Date.parse(entry.occurred_at)>Date.parse(index?orderHistory[index-1].occurred_at:auction.ends_at)))||
      Date.parse(orderHistory[1]?.occurred_at)!==noticeAt||!(attemptAt<baseDeadline)||
      (!active&&!(confirmationAt<extendedDeadline))||orderHistory.at(-1)?.revision!==boundOrder.revision||
      Date.parse(conversation.follow_up_due_at)!==Date.parse(auction.ends_at)+86400000||!Array.isArray(conversation.items)||
      conversation.items.some(message=>{
        const sentAt=Date.parse(message.sent_at);
        return message.author!=='buyer'||!(sentAt>=attemptAt&&sentAt<=Date.parse(auction.server_time))||
          (!active&&!(sentAt<confirmationAt));
      })) throw new Error('Unbound auction payment and support fixture');
    return {id:result.order_id,revision:boundOrder.revision,items:conversation.items};
  };
  const selector='form:has(textarea) button[type="submit"]';
  const text='Synthetic support reload text';
  const pending=locale==='ar'?'لم يتم تأكيد الرسالة بعد.':'The message is not yet confirmed.';
  await fetch(`${fixture}?reset=1&mode=${scenario}`);
  try {
    const heldOrder=await checkBinding('active');
    await page.open(won);await page.wait(contact);await page.click(contact);await page.wait('textarea');
    await page.fill('textarea',text);await page.click(selector);
    await until(`document.body.textContent.includes(${JSON.stringify(pending)})&&!document.querySelector(${JSON.stringify(selector)})?.disabled`);
    const storage=await page.eval(()=>Object.keys(sessionStorage).filter(key=>key.startsWith('bt.support-attempt.v1:')).map(key=>sessionStorage.getItem(key)));
    if(storage.length!==1||storage[0].includes(text)) throw new Error('Invalid retained support reference');
    for(let retry=0;retry<100&&(await (await fetch(fixture)).json()).supportDeliveries===0;retry++) await page.wait(100);
    const before=await (await fetch(fixture)).json();
    if(before.supportDeliveries!==1||before.supportSends!==Number(scenario==='support-committed')) throw new Error('Expected one uncertain delivery before reload');
    const committedItems=(await checkBinding('active')).items;
    if(committedItems.length!==before.supportSends||committedItems.some(message=>message.body!==text))
      throw new Error('Unexpected message before payment confirmation');
    const ongoing=scenario==='support-active-history';
    await page.eval(()=>{window.__oldSupportDocument=true;});
    if(ongoing){
      // A saved history address can be opened while this separate order is still held.
      const savedAddress=await page.eval(()=>{const href=new URL(location.href);href.searchParams.set('view','history');return href.href;});
      await page.open(won);await page.wait(contact);await page.open(savedAddress);
    }else{
      if(!(await fetch(`${fixture}?resolve-support=1`)).ok)throw new Error('Payment confirmation fixture failed');
      const settledOrder=await checkBinding('resolved');
      if(settledOrder.id!==heldOrder.id||settledOrder.revision!==heldOrder.revision+1) throw new Error('Auction order did not advance exactly in scope');
      await page.open(won);await page.wait(history);await page.click(history);
    }
    const checkText=locale==='ar'?'تحقّق من الرسالة السابقة':'Check previous message';
    await until(`[...document.querySelectorAll('main button')].some(button=>button.textContent.trim()===${JSON.stringify(checkText)})`);
    if(await page.eval(()=>window.__oldSupportDocument===true||!!document.querySelector('textarea'))) throw new Error('Expected fresh, read-only history');
    const checkAttempt=()=>page.eval(`Array.from(document.querySelectorAll('main button')).find(button=>button.textContent.trim()===${JSON.stringify(checkText)}).click()`);
    await checkAttempt();
    const feedback=ongoing?(locale==='ar'?'الرسالة السابقة محفوظة ولم تُرسل بعد.':'The previous message is saved but has not been sent.'):
      scenario==='support-committed'?(locale==='ar'?'تم تأكيد الرسالة':'Message confirmed'):
        (locale==='ar'?'لم تُرسل الرسالة السابقة.':'The previous message was not sent.');
    await until(`document.body.textContent.includes(${JSON.stringify(feedback)})`);
    const after=await (await fetch(fixture)).json();
    if(after.supportDeliveries!==1||after.supportSends!==before.supportSends) throw new Error('History delivered a message');
    const finalOrder=await checkBinding(ongoing?'active':'resolved');
    if(finalOrder.revision!==heldOrder.revision+(ongoing?0:1)||finalOrder.id!==heldOrder.id)throw new Error('History changed order state');
    if(JSON.stringify(finalOrder.items)!==JSON.stringify(committedItems))throw new Error('History changed the original message or its timestamp');
    const remaining=await page.eval(()=>Object.keys(sessionStorage).filter(key=>key.startsWith('bt.support-attempt.v1:')).map(key=>sessionStorage.getItem(key)));
    if(ongoing?(remaining.length!==1||remaining[0]!==storage[0]):remaining.length!==0) throw new Error('History changed the wrong retained attempt');
    return {freshDocument:true,historyRecovery:true,recordedMessages:after.supportSends};
  } finally {await fetch(fixture+'?reset=1');}
 });
 await check(`${locale}: availability and reservation, never payment`,async()=>{
  await fetch('http://127.0.0.1:33516/__proof?reset=1');
  await page.open(`${origin}/${locale}/checkout?watch=00000000-0000-4000-8000-000000000006&quote=${checkoutQuote}`);await page.wait('input[name="watch_id"]');
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
await check('shared theme switch uses the shared View Transition',async()=>{
 await page.eval(()=>{document.cookie='bt-theme=light; Path=/';});await page.open(`${origin}/en/buyer`);
 await until(`document.querySelector('h1')?.textContent.trim()==='My buying workspace'`);
 await page.eval(()=>{window.__buyerTransitions=0;const original=document.startViewTransition?.bind(document);if(original)document.startViewTransition=fn=>{window.__buyerTransitions++;return original(fn);};});
 await page.click('button[aria-label="Switch to dark theme"]');await until(`document.documentElement.dataset.theme==='dark'`);
 const state=await page.eval(()=>({theme:document.documentElement.dataset.theme,calls:window.__buyerTransitions,duration:getComputedStyle(document.documentElement,'::view-transition-old(root)').animationDuration}));
 if(state.theme!=='dark'||state.calls!==1)throw new Error('Theme did not use View Transition');return state;
});
console.log(JSON.stringify({synthetic:true,passed:results.every(r=>r.passed),results},null,2));
