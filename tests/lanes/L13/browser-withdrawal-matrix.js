const cases=[];
for(const language of ['en','ar'])for(const theme of ['light','dark']){
 await page.open(fixture.origin+'/'+language+'/seller/withdrawals');
 for(let i=0;i<100;i++){if(await page.eval(()=>document.querySelectorAll('.withdrawal-row').length>=2))break;await page.wait(200);}
 if(await page.eval(()=>document.documentElement.dataset.theme)!==theme){let snapshot=await page.snapshot(),opened=false;if(await page.eval(()=>innerWidth<=850)){await page.click('header .pg-mobile-menu');opened=true;snapshot=await page.snapshot();}const m=/uid=(\S+) button "(?:Switch to (?:dark|light) theme|التبديل إلى المظهر (?:الداكن|الفاتح))"/.exec(snapshot);if(!m)throw Error('Theme control missing '+snapshot);await page.click('@'+m[1]);await page.wait(600);if(opened)await page.press('Escape');}
 const state=await page.eval(()=>({lang:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,width:innerWidth,
 overflow:document.documentElement.scrollWidth>innerWidth,mainCount:document.querySelectorAll('main').length,history:document.querySelectorAll('.withdrawal-row').length,
 success:document.body.innerText.includes('Listing withdrawn. History is retained.')||document.body.innerText.includes('سُحب الإعلان مع الاحتفاظ بسجله.')}));
 if(state.width!==fixture.width||state.lang!==language||state.dir!==(language==='ar'?'rtl':'ltr')||state.theme!==theme||state.overflow||state.mainCount!==1||!state.success)throw Error('Withdrawal matrix failed '+JSON.stringify(state));
 await page.press('Tab');if(await page.eval(()=>document.activeElement===document.body))throw Error('Keyboard focus absent');cases.push({...state,keyboard:true});
}
console.log(JSON.stringify({cases,realBackends:true}));
