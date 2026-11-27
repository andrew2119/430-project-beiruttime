async function until(expression){for(let i=0;i<100;i++){if(await page.eval(expression))return;await page.wait(150);}throw Error('Timed out: '+expression+'\n'+await page.snapshot());}
const evidence=[];
for(const locale of ['en','ar'])for(const theme of ['light','dark']){
 await page.open(fixture.origin+'/'+locale+'/watches/'+fixture.auction.listingId);
 const expected=fixture.auction.allocation==='pending'?(locale==='ar'?'حُسم المزاد؛ تخصيص الطلب قيد المطابقة':'Auction decided; order allocation is reconciling'):(locale==='ar'?'أُغلق المزاد':'Auction closed');
 await until('document.body.innerText.includes('+JSON.stringify(expected)+')');
 if(await page.eval(()=>document.documentElement.dataset.theme)!==theme){
   let snapshot=await page.snapshot(),drawer=false;
   if(fixture.width===390){await page.click('header .pg-mobile-menu');drawer=true;snapshot=await page.snapshot();}
   const match=/uid=(\S+) button "(?:Switch to (?:dark|light) theme|التبديل إلى المظهر (?:الداكن|الفاتح))"/.exec(snapshot);
   if(!match)throw Error('Theme control missing');await page.click('@'+match[1]);await page.wait(500);if(drawer)await page.press('Escape');
 }
 const facts=await page.eval(()=>({width:innerWidth,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth,main:document.querySelectorAll('main').length}));
 if(facts.width!==fixture.width||facts.dir!==(locale==='ar'?'rtl':'ltr')||facts.theme!==theme||facts.overflow||facts.main!==1)throw Error('Auction slot layout failure '+JSON.stringify(facts));
 evidence.push({locale,theme,...facts});
}
console.log(JSON.stringify(evidence));
