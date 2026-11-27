// Real accounts and server operations; the only fault is discarding ONE actual
// successful network response AFTER the server has accepted the bid.
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
  await page.fill('input[name=email]',name+(CONTEXT.accountSuffix??'.l12@example.test'));
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
if(await page.eval(()=>!!document.querySelector('.auction-policy-form')))throw new Error('Fixed policy has an editable form');
await login('buyer-a');
const statusRoute='/auction-policy?listing_id='+CONTEXT.listing;
if(CONTEXT.width===1280) {
  const watchRoute=CONTEXT.origin+'/en/watches/'+CONTEXT.listing;
  await page.open(watchRoute);
  await page.wait('.auction-bid-form input[inputmode=decimal]');
  await page.fill('.auction-bid-form input[inputmode=decimal]','4000.00');
  await page.click('.auction-bid-form button[type=button]');
  await page.wait('.auction-fee-preview .auction-check input');
  await page.click('.auction-fee-preview .auction-check');
  await page.eval(()=>{
    const original=window.fetch.bind(window);
    let dropped=false;
    window.fetch=async function(input,init) {
      const response=await original(input,init);
      const url=input instanceof Request?input.url:String(input);
      const method=init?.method??(input instanceof Request?input.method:'GET');
      if(!dropped&&url.endsWith('/bids')&&method==='POST'&&response.ok) {
        dropped=true;window.__l12LostResponse=true;
        throw new TypeError('Explicit acceptance fault: discard committed reply');
      }
      return response;
    };
  });
  await page.click('.auction-bid-form button:last-child');
  await until(()=>{const panel=document.querySelector('.auction-bid-panel');return panel?.textContent.includes('Bid confirmed')||[...panel?.querySelectorAll('.auction-bid-form button')??[]].some(b=>b.textContent==='Try again'&&!b.disabled);},'Accepted bid or retained retry');
  await page.eval(()=>[...document.querySelectorAll('.auction-bid-form button')].find(b=>b.textContent==='Try again')?.click());
  await until(()=>document.querySelector('.auction-bid-panel')?.textContent.includes('Bid confirmed'),'Lost-response reconciliation');
  if(!await page.eval(()=>window.__l12LostResponse))throw new Error('Network fault was not exercised');
  await page.open(watchRoute);
  await until(()=>document.querySelectorAll('.auction-history li').length===1,'Fresh-page authoritative bid history');
}
await matrix(statusRoute,'buyer-fixed-policy');
await page.open(CONTEXT.origin+'/en'+statusRoute);
await until(()=>document.querySelector('main')?.textContent.includes('Auctions do not offer Buy Now.'),'Auction purchase excluded');
if(await page.eval(()=>!!document.querySelector('.auction-policy-form, a[href*="/checkout?order_id="]')))throw new Error('New auction exposed a purchase control');
if(CONTEXT.width===390) {
  await page.click('.pg-mobile-menu');await page.press('Escape');await page.wait(350);
  if(!await page.eval(()=>document.activeElement?.classList.contains('pg-mobile-menu')))throw new Error('Phone focus not restored');
}
console.log(JSON.stringify(checks,null,2));
