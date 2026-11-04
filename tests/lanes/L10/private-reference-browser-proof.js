// Execute after connected-browser-proof.js with a real current buyer/configuration.
// A synthetic 1px PNG exercises the actual browser input handler and real upload API;
// no session, response, dependency transport or private image URL is simulated.
await page.click('.bo-categories button:nth-child(3)');
const before=await page.eval(()=>Number(document.querySelector('.bo-summary section bdi')?.textContent));
await page.eval(()=>{
  const bytes=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNQcEgAAAFEAMELjZZCAAAAAElFTkSuQmCC'),character=>character.charCodeAt(0));
  const transfer=new DataTransfer();
  transfer.items.add(new File([bytes],'sample-reference.png',{type:'image/png'}));
  const input=document.querySelector('input[type=file]');
  input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));
});
await page.wait('.bo-private-images img');
await page.click('.bo-option input');await page.click('.bo-actions button');await page.wait(300);
let url=await page.eval(()=>location.href);
for(const locale of ['en','ar']) {
  url=url.replace(/\/(en|ar)\/customize/,`/${locale}/customize`);
  await page.open(url);await page.wait('.bo-saved');await page.click('.bo-categories button:nth-child(3)');await page.wait('.bo-private-images img');
  const result=await page.eval(()=>({locale:document.documentElement.lang,
    revision:Number(document.querySelector('.bo-summary section bdi')?.textContent),
    privateImage:document.querySelector('.bo-private-images img')?.src.startsWith('data:image/png;'),
    loaded:document.querySelector('.bo-private-images img')?.naturalWidth,
    errors:[...document.querySelectorAll('[role=alert]')].map(node=>node.textContent).filter(Boolean),
  }));
  if(result.revision!==before+1||!result.privateImage||!result.loaded||result.errors.length)throw new Error(JSON.stringify(result));
  console.log(JSON.stringify(result));
}
