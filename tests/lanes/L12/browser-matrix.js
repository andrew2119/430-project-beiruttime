const checks=[];
for(const locale of ['en','ar'])for(const theme of ['light','dark']) {
  await page.eval(`document.cookie='bt-theme=${theme}; Path=/; SameSite=Lax'`);
  for(const route of ['/auction-policy','/seller/auctions']) {
    const result=await page.open(`http://127.0.0.1:3412/${locale}${route}`);
    if(result.status!==200)throw new Error(`Unexpected page status ${result.status}`);
    await page.wait('h1');
    if(route==='/auction-policy')await page.wait('.auction-policy-panel');
    const check=await page.eval(()=>({path:location.pathname,width:innerWidth,locale:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,mainCount:document.querySelectorAll('main').length,overflow:document.documentElement.scrollWidth>innerWidth,heading:document.querySelector('h1')?.textContent,policies:document.querySelectorAll('.auction-policy-panel').length}));
    if(check.width!==WIDTH||check.locale!==locale||check.theme!==theme||check.dir!==(locale==='ar'?'rtl':'ltr')||check.mainCount!==1||check.overflow||!check.heading)throw new Error(JSON.stringify(check));
    checks.push(check);
  }
}
await page.open('http://127.0.0.1:3412/en/auction-policy');
await page.wait('.auction-policy-panel');
if(WIDTH===390) {
  await page.click('.pg-mobile-menu');
  await page.press('Escape');
  await page.wait(350);
  if(!await page.eval(()=>document.activeElement?.classList.contains('pg-mobile-menu')))throw new Error('Phone menu did not restore focus');
}
console.log(JSON.stringify(checks,null,2));
