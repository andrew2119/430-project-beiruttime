// Real controls against loopback synthetic transports; never production accounts.
const root='http://127.0.0.1:3357';
const proof=[];
async function until(expression){for(let i=0;i<80;i++){if(await page.eval(expression))return;await page.wait(50);}throw Error('Interaction did not settle: '+expression);}
for(const locale of ['en','ar']){
 await page.open(`${root}/${locale}/business/contacts`);await page.wait('input[name="recipient"]');
 await page.click('.business-form .ui-select');await page.wait('[role="menuitemradio"]');await page.click('[role="menuitemradio"][data-state="unchecked"]');
 if(await page.eval(()=>document.querySelector('select[name="channel"]').value)!=='phone')throw Error('Menu did not update native contact FormData');
 await page.fill('input[name="recipient"]','+٩٦١٧٠١٢٣٤٥٦');await page.fill('input[name="reauth"]','synthetic-password-not-a-credential');
 await page.click('form:has(input[name="recipient"]) button[type="submit"]');await page.wait('.business-proof');
 await page.click('.business-proof > button');await until(`!![...document.querySelectorAll('.business-proof bdi')].find(e=>e.textContent==='123456')`);
 await page.fill('input[name="code"]','١٢٣٤٥٦');await page.click('form:has(input[name="code"]) button[type="submit"]');
 await until(`!document.querySelector('.business-proof')`);proof.push({locale,contactCode:true,nativeFormData:true,arabicDigits:true});
 await page.open(`${root}/${locale}/business`);await page.wait('select[name="kind"]');
 if(await page.eval(()=>document.querySelector('select[name="kind"]').value)!=='brand'){await page.click('form:has(input[name="legal_name"]) .ui-select');await page.wait('[role="menuitemradio"]');await page.click('[role="menuitemradio"][data-state="unchecked"]');}
 if(await page.eval(()=>new FormData(document.querySelector('form:has(input[name="legal_name"])')).get('kind'))!=='brand')throw Error('Business type FormData failed');
 await page.eval(()=>document.querySelector('form:has(input[name="legal_name"])').reset());await page.wait(50);
 if(await page.eval(()=>document.querySelector('form:has(input[name="legal_name"]) .ui-select').dataset.value)!=='dealer')throw Error('Native reset did not reset the CP trigger');
 proof.push({locale,formReset:true});
 await page.open(`${root}/${locale}/operations/moderation`);await page.wait('.ops-form .ui-select');
 await page.fill('.ops-form input','00000000-0000-4000-8000-000000000008');await page.fill('.ops-form textarea','Sample report context for the browser proof only.');
 await page.click('.ops-form button[type="submit"]');await page.wait('.ops-private');proof.push({locale,reportAndCase:true});
 await page.open(`${root}/${locale}/business-intake`);await page.wait('.ops-form .ui-select');
 if(!await page.eval(()=>document.querySelector('label.ops-form select')?.value)){await page.click('label.ops-form .ui-select');await page.wait('[role="menuitemradio"]');await page.click('[role="menuitemradio"][data-state="unchecked"]');}
 await page.wait('.ops-records button');await page.click('.ops-records button');await page.wait('input[readonly]');
 const currency='.ops-field-grid label:has(select) .ui-select';
 if(await page.eval(()=>document.querySelector('.ops-field-grid select').value)!=='LBP'){await page.click(currency);await page.wait('[role="menuitemradio"]');await page.click('[role="menuitemradio"][data-state="unchecked"]');}
 await page.click('.ops-checks input');
 await page.fill('.ops-field-grid input[inputmode="numeric"]','٢٥٠٠');
 await page.click('.ops-form:has(input[readonly]) button[type="submit"]');
 await until(`!!document.querySelector('input[readonly]')&&!document.querySelector('fieldset[disabled]')`);proof.push({locale,intakeCurrency:true,checkbox:true,arabicFee:true});
}
console.log(JSON.stringify({proof},null,2));
