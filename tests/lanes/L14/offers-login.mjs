// Shared native-form helper for chrome-devtools-axi run; synthetic users only.
const base='http://127.0.0.1:3640';
async function login(email,password,accountPath='/en/account',readySelector='.identity-actions'){
 await page.open(base+accountPath);
 for(let i=0;i<80;i++){
  if(await page.eval(()=>!!document.querySelector('.identity-tabs')))break;
  await page.eval(()=>[...document.querySelectorAll('.identity-page button')].find(button=>button.textContent==='Sign out')?.click());
  await page.wait(100);
 }
 await page.eval(()=>[...document.querySelectorAll('.identity-tabs button')].find(button=>button.textContent==='Sign in')?.click());
 await page.wait('input[name=email]');
 await page.eval('()=>{for(const [name,value] of Object.entries('+JSON.stringify({email,password})+')){document.querySelector("input[name="+name+"]").value=value;}document.querySelector(".identity-form").requestSubmit();}');
 await page.wait(readySelector);
}
