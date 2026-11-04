const root='http://127.0.0.1:3357';
const form='form:has(input[name="legal_name"])';
await page.open(root+'/en/business');await page.wait(form);
await page.fill(form+' input[name="public_name"]','Sample public draft');
await page.fill(form+' input[name="legal_name"]','SYNTHETIC PRIVATE LEGAL NAME');
await page.fill(form+' input[name="assurance"]','SYNTHETIC PRIVATE ASSURANCE');
if(!await page.eval(()=>document.querySelector('input[value="servicing"]').checked))await page.click('input[value="servicing"]');
if(await page.eval(()=>document.querySelector('select[name="kind"]').value)!=='brand'){await page.click(form+' .ui-select');await page.wait('[role="menuitemradio"]');await page.click('[role="menuitemradio"][data-state="unchecked"]');}
for(const locale of ['ar','en']){
 await page.open(root+'/'+locale+'/business');await page.wait(form);
 const result=await page.eval(()=>{const f=document.querySelector('form:has(input[name="legal_name"])');return {publicName:f.elements.public_name.value,legal:f.elements.legal_name.value,assurance:f.elements.assurance.value,kind:f.elements.kind.value,trigger:f.querySelector('.ui-select').dataset.value,servicing:f.querySelector('input[value="servicing"]').checked};});
 if(result.publicName!=='Sample public draft'||result.legal||result.assurance||result.kind!=='brand'||result.trigger!=='brand'||!result.servicing)throw Error(JSON.stringify({locale,result}));
}
console.log(JSON.stringify({localeRoundTrip:true,capabilitiesPreserved:true,menuSynced:true,privateFieldsNotPersisted:true}));
