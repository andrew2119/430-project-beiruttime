// Run through CHROME_DEVTOOLS_AXI_SESSION=bt-cp-business chrome-devtools-axi run.
// Set the real viewport with `emulate` before each run (1440x1000 or 390x844).
const root='http://127.0.0.1:3357';
const org='00000000-0000-4000-8000-000000000003';
const caseId='00000000-0000-4000-8000-000000000007';
const routes=[
 ['business','/business','input[name="legal_name"]'],
 ['contacts','/business/contacts','input[name="recipient"]'],
 ['membership','/business/membership','input[name="subject"]'],
 ['history','/business/review-history','.business-timeline'],
 ['verification','/operations/verification','.business-queue button'],
 ['intake','/business-intake','.ops-form .ui-select'],
 ['moderation','/operations/moderation?case='+caseId,'.ops-private'],
 ['dashboard','/operations/dashboard','.ops-queue-grid .ui-card'],
 ['queue','/operations/dashboard/queues/inspection','.ops-queue-grid .ui-card'],
];
await page.open(root+'/en/business');
await page.wait('input[name="legal_name"]');
const viewport=await page.eval(()=>innerWidth);
const results=[];
for(const locale of ['en','ar'])for(const theme of ['light','dark']) {
 await page.eval(`document.cookie='bt-theme=${theme}; Path=/; SameSite=Lax'`);
 for(const [name,path,ready] of routes) {
  await page.open(root+'/'+locale+path); await page.wait(ready);
  if(name==='membership') {
   await page.fill('form:not(:has(input[name="subject"])) input[name="business"]',org);
   await page.click('form:not(:has(input[name="subject"])) button[type="submit"]');
   await page.wait('.business-content .ui-badge');
  }
  if(name==='verification') {
   await page.click('.business-queue button');await page.wait('input[name="application_revision"]');
  }
  if(name==='intake') {
   const selected=await page.eval(()=>document.querySelector('label.ops-form select')?.value);
   if(!selected) {await page.click('label.ops-form .ui-select');await page.wait('[role="menuitemradio"]');await page.click('[role="menuitemradio"][data-state="unchecked"]');}
   await page.wait('.ops-records button');await page.click('.ops-records button');await page.wait('input[readonly]');
  }
  await page.press('Tab');
  await page.eval(()=>{document.querySelector('main :is(.ui-input,.ui-select,.ui-btn)')?.focus();});
  const data=await page.eval(()=>{
   const title=document.querySelector('main .hx-title');
   const active=document.activeElement;
   const fit=[...document.querySelectorAll('main *')].filter(e=>{const r=e.getBoundingClientRect();return !e.closest('[aria-hidden="true"]')&&r.width>0&&(r.right>innerWidth+1||r.left< -1)&&getComputedStyle(e).position!=='absolute';}).map(e=>String(e.className)).slice(0,8);
   const clippedTabs=[...document.querySelectorAll('.hx-tabs:not(.hx-tabs-ruler) > .hx-tab')].filter(e=>e.scrollWidth>e.clientWidth+1).map(e=>e.textContent);
   return {viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth,theme:document.documentElement.dataset.theme,dir:document.documentElement.dir,title:title?.textContent,font:getComputedStyle(title).fontFamily,focusOutline:getComputedStyle(active).outlineStyle,focusShadow:getComputedStyle(active).boxShadow,clippedTabs,inputs:[...document.querySelectorAll('main input:not([type="hidden"]):not([type="checkbox"])')].map(e=>parseFloat(getComputedStyle(e).fontSize)),fit};
  });
  if(data.viewport!==viewport||data.scrollWidth>viewport||data.theme!==theme||data.dir!==(locale==='ar'?'rtl':'ltr'))throw Error(JSON.stringify({name,locale,theme,data}));
  if(data.clippedTabs.length)throw Error('Clipped navigation: '+JSON.stringify({name,locale,theme,data}));
  if(viewport===390&&data.inputs.some(n=>n<16))throw Error('Small phone field: '+JSON.stringify({name,locale,theme,data}));
  results.push({name,locale,theme,...data});
 }
}
console.log(JSON.stringify({viewport,checks:results.length,results},null,2));
