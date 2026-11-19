// Real accounts and server operations; the only fault is discarding ONE actual
// successful network response AFTER the server has processed the purchase.
const checks=[];
async function until(expression,label) {
  for(let i=0;i<150;i++) {if(await page.eval(expression))return;await page.wait(200);}
  throw new Error(label+': '+await page.eval(()=>document.querySelector('main')?.innerText));
}
async function login(name) {
  await page.open(CONTEXT.origin+'/en/account');
  await page.wait('.identity-page');
  await page.wait(600);
  if(!await page.eval(()=>!!document.querySelector('input[name=email]'))) {
    await page.eval(()=>[...document.querySelectorAll('.identity-page button')].find(b=>b.textContent==='Sign out')?.click());
  }
  await page.wait('input[name=email]');
  await page.fill('input[name=email]',name+'.l12@example.test');
  await page.fill('input[name=password]',CONTEXT.password);
  await page.click('.identity-form button');
  await until(()=>!document.querySelector('input[name=email]'),'Authenticated account view');
}
function facts() {return {width:innerWidth,locale:document.documentElement.lang,dir:document.documentElement.dir,
  theme:document.documentElement.dataset.theme,main:document.querySelectorAll('main').length,
  overflow:document.documentElement.scrollWidth>innerWidth+1,panels:document.querySelectorAll('.auction-policy-panel').length,
  heading:document.querySelector('h1')?.textContent};}
async function matrix(route,role) {
  for(const locale of ['en','ar'])for(const theme of ['light','dark']) {
    await page.eval(`document.cookie='bt-theme=${theme};Path=/;SameSite=Lax'`);
    await page.open(`${CONTEXT.origin}/${locale}${route}`);
    await page.wait('.auction-policy-panel');
    await page.wait(400);
    const check=await page.eval(facts);
    if(check.width!==CONTEXT.width||check.locale!==locale||check.dir!==(locale==='ar'?'rtl':'ltr')||check.theme!==theme||check.main!==1||check.overflow||!check.heading)throw new Error(JSON.stringify(check));
    checks.push({role,...check});
  }
}
await login('seller');
await matrix('/seller/auctions','seller');
if(CONTEXT.width===1280) {
  await page.open(CONTEXT.origin+'/en/seller/auctions');
  await page.wait('.auction-policy-form input');
  await page.fill('.auction-policy-form input','5000.00');
  await page.click('.auction-policy-form button[type=submit]');
  await until(()=>document.querySelector('.auction-policy-panel')?.innerText.includes('Policy confirmed.'),'Seller policy save');
}
await login('buyer-a');
const statusRoute='/auction-policy?listing_id='+CONTEXT.listing;
if(CONTEXT.width===1280) {
  await page.open(CONTEXT.origin+'/en'+statusRoute);
  await page.wait('.auction-policy-form button');
  await page.click('.auction-policy-form button');
  await page.wait('.auction-policy-form input[type=checkbox]');
  await page.click('.auction-policy-form input[type=checkbox]');
  await page.eval(()=>{
    const original=window.fetch.bind(window);
    let dropped=false;
    window.fetch=async function(input,init) {
      const response=await original(input,init);
      if(!dropped&&String(input).endsWith('/prebid-buy-now')&&init?.method==='POST'&&response.ok) {
        dropped=true;window.__l12LostResponse=true;
        throw new TypeError('Explicit acceptance fault: discard committed reply');
      }
      return response;
    };
  });
  await page.click('.auction-policy-form button:last-child');
  await until(()=>document.querySelector('main')?.innerText.includes('Reservation confirmed.'),'Lost-response reconciliation');
  if(!await page.eval(()=>window.__l12LostResponse))throw new Error('Network fault was not exercised');
  // Reload discards in-memory operation state. The private server lookup restores it.
  await page.open(CONTEXT.origin+'/en'+statusRoute);
  await until(()=>!!document.querySelector('a[href*="/checkout?order_id="]'),'Fresh-page private receipt');
}
await matrix(statusRoute,'buyer-receipt');
if(CONTEXT.width===390) {
  await page.click('.pg-mobile-menu');await page.press('Escape');await page.wait(350);
  if(!await page.eval(()=>document.activeElement?.classList.contains('pg-mobile-menu')))throw new Error('Phone focus not restored');
}
console.log(JSON.stringify(checks,null,2));
