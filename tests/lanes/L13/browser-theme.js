const selector=fixture.selector??'.payment-fees,.withdrawal-row';
for(let i=0;i<100;i++){if(await page.eval('document.querySelector('+JSON.stringify(selector)+')!==null'))break;await page.wait(100);}
if(!await page.eval('document.querySelector('+JSON.stringify(selector)+')!==null'))throw Error('Authenticated screenshot content missing');
if(await page.eval(()=>document.documentElement.dataset.theme)!==fixture.theme){
 let snapshot=await page.snapshot(),opened=false;
 if(await page.eval(()=>innerWidth<=850)){await page.click('header .pg-mobile-menu');opened=true;snapshot=await page.snapshot();}
 const m=/uid=(\S+) button "(?:Switch to (?:dark|light) theme|التبديل إلى المظهر (?:الداكن|الفاتح))"/.exec(snapshot);
 if(!m)throw Error('Theme control missing '+snapshot);await page.click('@'+m[1]);await page.wait(600);if(opened)await page.press('Escape');
}
