// Real same-origin BFF, Identity sessions and domain operations; no transport interception.
async function until(expression){for(let i=0;i<100;i++){if(await page.eval(expression))return;await page.wait(200);}throw Error('Timed out: '+expression);}
async function clickText(label){
  const snapshot=await page.snapshot();
  const escaped=label.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const match=new RegExp('uid=(\\S+) (?:button|link) "'+escaped+'"').exec(snapshot);
  if(!match)throw Error('Control missing: '+label+'\n'+snapshot);
  await page.click('@'+match[1]);
}
await page.open(fixture.origin+'/en/account');
await page.wait('input[name=email]');
await page.fill('input[name=email]',fixture.buyerEmail);
await page.fill('input[name=password]',fixture.password);
await clickText('Continue');
await until("document.body.innerText.includes('Your account')");
await page.open(fixture.origin+'/en/checkout?listing_id='+fixture.purchaseListing);
await until("document.body.innerText.includes('Get current exact quote')");
await clickText('Get current exact quote');
await until("document.body.innerText.includes('Exact quote ready for review')");
if(!await page.eval(()=>document.querySelector('.payment-fees')?.textContent.includes('5,150.00')))throw Error('Exact total missing');
const retainedSelection=await page.eval(()=>sessionStorage.getItem(Object.keys(sessionStorage).find(key=>key.startsWith('bt-draft:')&&key.endsWith(':checkout-quote'))));
if(!retainedSelection)throw Error('Owned non-secret quote selection missing');
await page.open(fixture.origin+'/ar/checkout?listing_id='+fixture.purchaseListing);
await until("document.body.innerText.includes('عرض سعر دقيق جاهز للمراجعة')");
if(await page.eval(()=>document.querySelector('input[type=checkbox]').checked))throw Error('Locale change silently accepted a quote');
await page.open(fixture.origin+'/en/checkout?listing_id='+fixture.purchaseListing);
await until("document.body.innerText.includes('Exact quote ready for review')");
if(await page.eval(()=>sessionStorage.getItem(Object.keys(sessionStorage).find(key=>key.startsWith('bt-draft:')&&key.endsWith(':checkout-quote'))))!==retainedSelection)throw Error('Exact quote selection changed across locale navigation');
await page.click('input[type=checkbox]');
await clickText('Accept exact quote and reserve');
await until("document.body.innerText.includes('Continue to simulated payment')");
await clickText('Continue to simulated payment');
await until("document.body.innerText.includes('Create simulated attempt')");
await clickText('Create simulated attempt');
await until("document.body.innerText.includes('Simulate confirmation')");
await clickText('Simulate confirmation');
await until("document.body.innerText.includes('Simulated payment confirmed once')");
await until("document.querySelector('.checkout-history')?.textContent.includes('Signed simulated payment confirmed — funds held')");
const orderId=await page.eval(()=>location.pathname.split('/').at(-1));
console.log(JSON.stringify({realIdentity:true,realPricing:true,realOrders:true,orderId,exactTotalMinor:515000,simulated:true}));
