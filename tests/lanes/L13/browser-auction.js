// Canonical real auction result slot and its own winner checkout link.
async function until(expression){for(let i=0;i<100;i++){if(await page.eval(expression))return;await page.wait(200);}throw Error('Timed out: '+expression+'\n'+await page.snapshot());}
async function clickText(label){const snapshot=await page.snapshot();const escaped=label.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');const match=new RegExp('uid=(\\S+) (?:button|link) "'+escaped+'"').exec(snapshot);if(!match)throw Error('Control missing: '+label+'\n'+snapshot);await page.click('@'+match[1]);}
if(fixture.winnerCheckoutOnly){
  await page.open(fixture.origin+'/en/checkout');
  const href='/en/checkout/'+fixture.auction.orderId;
  await until('document.querySelector(\'a[href="'+href+'"]\')!==null');
  await page.click('a[href="'+href+'"]');
}else{
  await page.open(fixture.origin+'/en/watches/'+fixture.auction.listingId);
  await until("document.body.innerText.includes('Auction result')");
}
if(fixture.auction.allocation==='pending'){
  await until("document.body.innerText.includes('Auction decided; order allocation is reconciling')");
  if(await page.eval(()=>[...document.querySelectorAll('a')].some(a=>a.textContent==='Continue to simulated payment')))throw Error('Unconfirmed allocation exposed a payment link');
  console.log(JSON.stringify({connectedWinner:true,allocation:'pending',noInventedPayment:true}));
}else{
  if(!fixture.winnerCheckoutOnly){
    await until("document.body.innerText.includes('Auction closed') && document.body.innerText.includes('Continue to simulated payment')");
    await clickText('Continue to simulated payment');
  }
  await until("document.body.innerText.includes('Create simulated attempt')");
  if(!await page.eval(()=>document.querySelector('.payment-fees')?.textContent.includes('5,150.00')))throw Error('Exact winner economics missing');
  if(!await page.eval(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='Create simulated attempt')?.disabled))throw Error('Unreviewed winner total was payable without explicit acceptance');
  await page.click('input[type=checkbox]');
  await clickText('Create simulated attempt');
  await until("document.body.innerText.includes('Simulate confirmation')");
  await clickText('Simulate confirmation');
  await until("document.body.innerText.includes('Simulated payment confirmed once')");
  await until("document.querySelector('.checkout-history')?.textContent.includes('Order allocation confirmed — awaiting payment') && document.querySelector('.checkout-history')?.textContent.includes('Signed simulated payment confirmed — funds held')");
  console.log(JSON.stringify({connectedWinner:true,allocation:'succeeded',explicitExactReview:true,simulatedPaid:true}));
}
