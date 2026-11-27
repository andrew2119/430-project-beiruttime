async function until(expression){for(let i=0;i<100;i++){if(await page.eval(expression))return;await page.wait(200);}throw Error('Timed out: '+expression+'\n'+await page.snapshot());}
async function clickText(label){const s=await page.snapshot();const escaped=label.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');const m=new RegExp('uid=(\\S+) (?:button|link) "'+escaped+'"').exec(s);if(!m)throw Error('Control missing: '+label+'\n'+s);await page.click('@'+m[1]);}
await page.open(fixture.origin+'/en/account');
await until("document.body.innerText.includes('Sign out')");await clickText('Sign out');
await page.wait('input[name=email]');await page.fill('input[name=email]',fixture.sellerEmail);await page.fill('input[name=password]',fixture.password);await clickText('Continue');
await until("document.body.innerText.includes('Your account')");
await page.open(fixture.origin+'/en/seller/withdrawals');
await until("document.querySelectorAll('.withdrawal-row').length>0");
// Select by the actual listing context instead of entering a copied command reference.
await page.eval("[...document.querySelectorAll('.withdrawal-row')].find(r=>r.textContent.includes("+JSON.stringify(fixture.withdrawListing)+")).querySelector('button').click()");
await page.wait('#withdrawal-reason');await page.click('#withdrawal-reason');await page.type('Synthetic sample no longer available');await page.press('Tab');
await until("!document.querySelector('[role=dialog] button[type=submit]').disabled");await clickText('Confirm withdrawal');
await until("document.body.innerText.includes('Listing withdrawn. History is retained.')");
await page.eval("[...document.querySelectorAll('.withdrawal-row')].find(r=>r.textContent.includes("+JSON.stringify(fixture.purchaseListing)+")).querySelector('button').click()");
await page.wait('#withdrawal-reason');await page.click('#withdrawal-reason');await page.type('Attempt against existing paid commitment');await page.press('Tab');
await until("!document.querySelector('[role=dialog] button[type=submit]').disabled");await clickText('Confirm withdrawal');
await until("document.body.innerText.includes('Withdrawal refused')");
console.log(JSON.stringify({withdrawn:fixture.withdrawListing,paidWithdrawalDenied:true,realIdentity:true,realCatalog:true,realOrders:true}));
