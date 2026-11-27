const cases=[];
for(const language of ['en','ar'])for(const theme of ['light','dark']){
  await page.open(fixture.origin+'/'+language+'/checkout/'+fixture.orderId);
  for(let i=0;i<100;i++){if(await page.eval(()=>document.querySelector('.payment-fees')!==null))break;await page.wait(200);}
  if(await page.eval(()=>document.documentElement.dataset.theme)!==theme){
    let snapshot=await page.snapshot(),opened=false;
    if(await page.eval(()=>innerWidth<=850)){await page.click('header .pg-mobile-menu');opened=true;snapshot=await page.snapshot();}
    const match=/uid=(\S+) button "(?:Switch to (?:dark|light) theme|التبديل إلى المظهر (?:الداكن|الفاتح))"/.exec(snapshot);
    if(!match)throw Error('Theme control missing '+snapshot);await page.click('@'+match[1]);await page.wait(600);if(opened)await page.press('Escape');
  }
  const state=await page.eval(()=>({lang:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,
    width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,total:document.querySelector('.payment-fees')?.textContent,
    mainCount:document.querySelectorAll('main').length,paid:document.body.innerText.includes('Simulated payment confirmed once')||document.body.innerText.includes('تأكد الدفع التجريبي مرة واحدة')}));
  if(state.lang!==language||state.dir!==(language==='ar'?'rtl':'ltr')||state.theme!==theme||state.width!==fixture.width||state.overflow||state.mainCount!==1||!state.paid)throw Error('Matrix failed '+JSON.stringify(state));
  await page.press('Tab');if(await page.eval(()=>document.activeElement===document.body))throw Error('Keyboard focus absent');
  cases.push({...state,keyboard:true});
}
console.log(JSON.stringify({cases,realBackends:true,simulatedPayment:true}));
