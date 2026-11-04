// Executed by chrome-devtools-axi run, against the production image.
const checks=[];
for(const locale of ['en','ar']) for(const theme of ['light','dark']) {
  await page.eval(`document.cookie='bt-theme=${theme}; Path=/; SameSite=Lax'`);
  for(const route of ['', '/about']) {
    const result=await page.open(`http://localhost:3000/${locale}${route}`);
    if(result.status!==200) throw new Error(`Unexpected page status ${locale}/${theme}/${route}: ${result.status}`);
    await page.wait(route ? '.state h1' : '.hero h1');
    if(!route) await page.wait('.service-grid');
    const check=await page.eval(()=>{
      const root=document.documentElement, main=document.querySelector('main'), bottom=document.querySelector('.bottom-nav');
      const rect=main.getBoundingClientRect(), nav=bottom.getBoundingClientRect();
      return {path:location.pathname,width:innerWidth,height:innerHeight,dpr:devicePixelRatio,locale:root.lang,dir:root.dir,theme:root.dataset.theme,
        heading:document.querySelector('h1').textContent,overflow:document.body.scrollWidth>innerWidth||main.scrollWidth>main.clientWidth,
        phone:innerWidth<=850,navVisible:getComputedStyle(bottom).display!=='none',separated:rect.bottom<=nav.top,
        targetSizes:[...document.querySelectorAll('.bottom-nav a,.bottom-nav button,.preferences a,.preferences button')].filter(n=>n.getBoundingClientRect().width>0).map(n=>({w:n.getBoundingClientRect().width,h:n.getBoundingClientRect().height})),
        services:[...document.querySelectorAll('.service-grid .status-dot')].map(n=>n.classList.contains('ready'))};
    });
    if(check.locale!==locale||check.theme!==theme||check.dir!==(locale==='ar'?'rtl':'ltr')||check.overflow||!check.heading) throw new Error(JSON.stringify(check));
    if(check.phone&&(!check.navVisible||!check.separated||check.targetSizes.some(t=>t.w<44||t.h<44))) throw new Error('Phone geometry: '+JSON.stringify(check));
    if(!route&&(check.services.length!==9||check.services.some(s=>!s))) throw new Error('Healthy services expected: '+JSON.stringify(check));
    checks.push(check);
  }
}
const phone=await page.eval(()=>innerWidth<=850);
if(phone) {
  await page.open('http://localhost:3000/en'); await page.wait('.hero');
  await page.click('.bottom-menu');
  if(!await page.eval(()=>document.querySelector('dialog').open&&document.querySelector('dialog').contains(document.activeElement))) throw new Error('Dialog did not receive focus');
  await page.press('Escape'); await page.wait(50);
  if(!await page.eval(()=>!document.querySelector('dialog').open&&document.activeElement.classList.contains('bottom-menu'))) throw new Error('Escape did not restore trigger focus');
  await page.click('.top-menu'); await page.press('Escape'); await page.wait(50);
  if(!await page.eval(()=>!document.querySelector('dialog').open&&document.activeElement.classList.contains('top-menu'))) throw new Error('Escape did not restore top trigger focus');
  await page.click('.bottom-menu'); await page.click('.phone-drawer a[href="/en/about"]'); await page.wait('.state'); await page.wait(100);
  if(!await page.eval(()=>location.pathname==='/en/about'&&document.activeElement.id==='main-content'&&!document.querySelector('dialog').open)) throw new Error('Route focus was not handed to main');
  await page.click('.locale-control'); await page.wait('.state');
  if(!await page.eval(()=>location.pathname==='/ar/about'&&document.documentElement.dir==='rtl')) throw new Error('Locale switch lost the route or direction');
  checks.push({phoneMenu:'focus, Escape, destination focus and route-preserving locale switch passed'});
}
console.log(JSON.stringify(checks,null,2));
