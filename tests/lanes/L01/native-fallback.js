// Exercise native form submission, which does not invoke React's onSubmit handler.
await page.open('http://localhost:3101/en/account');
await page.wait('.identity-page');
for(let attempt=0;attempt<50;attempt++) {
  const loaded=await page.eval(()=>Boolean(document.querySelector('.identity-tabs')||document.querySelector('input[name=current_password]'))&&!document.querySelector('.identity-page [role=status]'));
  if(loaded)break;
  await page.wait(100);
}
await page.eval(()=>[...document.querySelectorAll('button')].find(x=>x.textContent==='Sign out')?.click());
await page.wait('input[name=email]');
for(let attempt=0;attempt<50;attempt++) {
  if(await page.eval(()=>!document.querySelector('form button').disabled))break;
  await page.wait(100);
}
if(await page.eval(()=>Boolean(document.querySelector('.identity-page [role=alert]'))))throw new Error('Sign-out must be acknowledged before the native fallback proof');
const method=await page.eval(()=>document.querySelector('form').method);
if(method!=='post')throw new Error('Private native fallback must never use GET');
await page.eval(()=>{
  const form=document.querySelector('form');
  form.elements.namedItem('email').value='native-fallback@example.test';
  form.elements.namedItem('password').value='Synthetic-Native-Private-Phrase';
  form.submit();
});
await page.wait(700);
const result=await page.eval(()=>({url:location.href,query:location.search,containsPrivatePhrase:document.body.textContent.includes('Synthetic-Native-Private-Phrase'),claimsSignedIn:document.querySelector('h1')?.textContent==='Welcome back'}));
if(result.query.includes('password')||result.query.includes('email')||result.containsPrivatePhrase||result.claimsSignedIn)throw new Error('Native fallback leaked or claimed an unacknowledged action');
console.log(JSON.stringify({method,...result},null,2));
