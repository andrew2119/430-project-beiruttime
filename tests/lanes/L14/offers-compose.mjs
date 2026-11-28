// Native authenticated entry is always exercised. Shared guest-return coverage
// is an explicit extra gate after the Identity owner publishes its allowlist.
if(context.check_guest_return){
 await page.open(base+'/en/offers?listing='+context.listing_id);
 await page.wait('.l14-desk a[href*="account"]');
 const signInHref=await page.eval(()=>document.querySelector('.l14-desk a[href*="account"]').getAttribute('href'));
 const signIn=new URL(signInHref,base);
 if(signIn.origin!==base||signIn.searchParams.get('next')!=='/offers?listing='+context.listing_id)throw new Error('Guest offer context was not retained');
 await login(context.buyer_email,context.buyer_password,signIn.pathname+signIn.search,'input[name=offer-amount]');
}else{
 await login(context.buyer_email,context.buyer_password);
 await page.open(base+'/en/watches/'+context.listing_id);
 const offerLink='a[href="/en/offers?listing='+context.listing_id+'"]';
 await page.wait(offerLink);
 await page.eval('()=>document.querySelector('+JSON.stringify(offerLink)+').click()');
 await page.wait('input[name=offer-amount]');
}
console.log(JSON.stringify({listing_id:context.listing_id,phase:'compose',guest_return_checked:!!context.check_guest_return}));
