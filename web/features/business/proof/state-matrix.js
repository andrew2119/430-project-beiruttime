// Set fixture /__proof?mode=empty|error|slow and body.dataset.proofMode before run.
const mode=await page.eval(()=>document.body.dataset.proofMode??'error');
const root='http://127.0.0.1:3357';
const records=[];
const paths=['/business','/business/contacts','/business/membership','/business/review-history','/operations/verification','/business-intake','/operations/moderation','/operations/dashboard','/operations/dashboard/queues/inspection'];
for(const locale of ['en','ar'])for(const path of paths){
 if(mode==='empty'&&['/business/contacts','/operations/dashboard/queues/inspection'].includes(path))continue;
 await page.open(root+'/'+locale+path);
 if(path==='/business/membership'){
  await page.wait('input[name="subject"]');await page.fill('form:not(:has(input[name="subject"])) input[name="business"]','00000000-0000-4000-8000-000000000003');await page.click('form:not(:has(input[name="subject"])) button[type="submit"]');
 }
 if(path==='/business-intake'){
  await page.wait('label.ops-form .ui-select');
  if(!await page.eval(()=>document.querySelector('label.ops-form select')?.value)){await page.click('label.ops-form .ui-select');await page.wait('[role="menuitemradio"]');await page.click('[role="menuitemradio"][data-state="unchecked"]');}
 }
 const selector=mode==='error'?'.business-feedback[role="alert"],.ops-notice[role="alert"]':mode==='slow'?'.business-loading,.ops-loading':'.business-content .state,.ops-content .state';
 await page.wait(selector);
 records.push({locale,path,mode,visible:await page.eval(`!!document.querySelector(${JSON.stringify(selector)})`)});
}
console.log(JSON.stringify({mode,checks:records.length,records},null,2));
