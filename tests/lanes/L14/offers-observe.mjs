// chrome-devtools-axi run input; proof contains only owned opaque references.
const composing=proof.phase==='compose';
if(composing)await page.wait('input[name=offer-amount]');
else{
 await page.wait('[data-offer-id="'+proof.offer_id+'"]');
 await page.wait('[data-offer-compose] [data-kind=empty]');
}
const result=await page.eval(()=>({viewport:innerWidth,locale:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,
 heading:document.querySelector('.l14-desk h1')?.textContent,overflow:document.documentElement.scrollWidth>innerWidth,
 offers:[...document.querySelectorAll('[data-offer-id]')].map(card=>({id:card.dataset.offerId,text:card.textContent})),composable:!!document.querySelector('input[name=offer-amount]'),
 compose_text:document.querySelector('[data-offer-compose]')?.textContent}));
if(result.overflow||result.composable!==composing||(!composing&&!result.offers.length))throw new Error('Populated private offer layout/state failed: '+JSON.stringify(result));
const target=composing?'[data-offer-compose]':'[data-offer-id="'+proof.offer_id+'"]';
await page.eval('()=>document.querySelector('+JSON.stringify(target)+').scrollIntoView({block:"center"})');
await page.wait(150);
console.log(JSON.stringify(result,null,2));
