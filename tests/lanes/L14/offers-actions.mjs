// chrome-devtools-axi run input; context is a synthetic native-login fixture.
// No direct API calls, bearer injection or financial browser persistence.
await login(context.buyer_email,context.buyer_password);
await page.open(base+'/en/offers?listing='+context.listing_id);
await page.wait('input[name=offer-amount]');
await page.eval(()=>{const input=document.querySelector('input[name=offer-amount]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'90.00');input.dispatchEvent(new Event('input',{bubbles:true}));});
await page.wait(100);
await page.eval(()=>document.querySelector('.l14-form').requestSubmit());
await page.wait('[data-offer-compose] .l14-fees');
const preview=await page.eval(()=>document.querySelector('[data-offer-compose] .l14-fees').textContent);
if(!preview.includes('90.00')||!preview.includes('2.70')||!preview.includes('92.70'))throw new Error('Exact real fee preview missing: '+preview);
await page.eval(()=>[...document.querySelectorAll('[data-offer-compose] button')].find(button=>button.textContent==='Send this offer').click());
let offerId=null;
for(let i=0;i<100;i++){
 offerId=await page.eval('()=>[...document.querySelectorAll("[data-offer-id]")].find(card=>[...card.querySelectorAll("a")].some(a=>a.getAttribute("href")==="/en/watches/'+context.listing_id+'"))?.dataset.offerId');
 if(offerId)break;
 await page.wait(100);
}
if(!offerId)throw new Error('Real buyer offer was not re-read after native submission');
await login(context.seller_email,context.seller_password);
await page.open(base+'/en/offers');
const selector='[data-offer-id="'+offerId+'"]';
const cardQuery='document.querySelector('+JSON.stringify(selector)+')';
await page.wait(selector);
await page.eval('()=>[...'+cardQuery+'.querySelectorAll("button")].find(button=>button.textContent==="Accept and reserve once").click()');
let accepted=false;
for(let i=0;i<100;i++){
 accepted=await page.eval('()=>'+cardQuery+'?.textContent.includes("Accepted")');
 if(accepted)break;
 await page.eval('()=>[...'+cardQuery+'.querySelectorAll("button")].find(button=>button.textContent.includes("Reconcile"))?.click()');
 await page.wait(150);
}
if(!accepted)throw new Error('Actual seller acceptance did not resolve to an accepted offer');
const orderHref=await page.eval('()=>[...'+cardQuery+'.querySelectorAll("a")].find(a=>a.getAttribute("href")?.startsWith("/en/checkout/"))?.getAttribute("href")');
if(!orderHref||!/^\/en\/checkout\/[a-f0-9-]{36}$/.test(orderHref))throw new Error('Canonical scoped order link missing');
await login(context.buyer_email,context.buyer_password);
await page.open(base+orderHref);
await page.wait('.checkout-result');
const order=await page.eval(()=>document.querySelector('.checkout-result').textContent);
if(!order.includes('Awaiting payment')||!order.includes('92.70'))throw new Error('Real scoped awaiting-payment review missing: '+order);
console.log(JSON.stringify({offer_id:offerId,listing_id:context.listing_id,order_href:orderHref,state:'accepted',payment_invoked:false},null,2));
