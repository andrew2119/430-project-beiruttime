// Real published Accounts routes + real care APIs/SQL; business/staff onboarding stays a V1 fixture.
const brand='00000000-0011-4000-8000-000000000001';
const address=locale=>`http://127.0.0.1:3111/${locale}/services?business=${brand}`;
const account=`http://127.0.0.1:3111/en/account?next=${encodeURIComponent(`/services?business=${brand}`)}`;
async function ready(selector){
  await page.wait(selector,10000);
  if(await page.eval(`()=>Boolean(document.querySelector(${JSON.stringify(selector)}))`)!==true)throw new Error(`Expected screen state missing: ${selector}`);
}
async function typeField(selector,value){
  const focused=await page.eval(`()=>{const input=document.querySelector(${JSON.stringify(selector)});if(!input||input.disabled)return false;input.focus();input.select();return document.activeElement===input;}`);
  if(focused!==true)throw new Error(`Cannot edit inactive field: ${selector}`);
  await page.type(value);
}
async function createBuyer(){
  // Exercise the merged registration and sign-in forms, never inject a token or session.
  const email=`care-${crypto.randomUUID()}@example.invalid`,password=`Care-Proof-${crypto.randomUUID()}`;
  await page.open(account);
  const logout='.identity-grid > .identity-stack > .card:first-child > .identity-stack > button';
  await ready(`.identity-tabs button:not([disabled]),${logout}:not([disabled])`);
  if(await page.eval(`()=>Boolean(document.querySelector(${JSON.stringify(logout)}))`))await page.click(logout);
  await ready('.identity-tabs button:not([disabled])');
  await page.click('.identity-tabs button:nth-child(2)');
  await ready('.identity-form input[name="display_name"]');
  await typeField('.identity-form input[name="display_name"]','Demo care buyer');
  await typeField('.identity-form input[name="email"]',email);
  await typeField('.identity-form input[name="password"]',password);
  await page.click('.identity-form > button');
  await ready('.directory-detail > .card form > button:not([disabled])');
  await page.open(account);
  await ready(logout);
  await page.click(logout);
  await ready('.identity-tabs button:not([disabled])');
  await typeField('.identity-form input[name="email"]',email);
  await typeField('.identity-form input[name="password"]',password);
  await page.click('.identity-form > button');
  await ready('.directory-detail > .card form > button:not([disabled])');
  if(await page.eval(()=>document.cookie.includes('bt_refresh=')))throw new Error('Refresh credential became script-readable');
}
async function checkConsentOutage(){
  // Real merged consent code + fresh principal/SQL; no canonical request means no recorded decision.
  const consent='http://127.0.0.1:3111/en/consent';
  await page.open(consent);
  await page.wait('.identity-form input[name="request_id"]');
  await page.wait('.identity-grid > .identity-stack > .card:nth-child(2) > p:not([role])');
  await typeField('.identity-form input[name="request_id"]',crypto.randomUUID());
  await typeField('.identity-form input[name="brand_id"]',brand);
  await page.click('.consent-choices input[value="refuse"]');
  await page.wait('.identity-form > button:not([disabled])');
  await page.click('.identity-form > button');
  await page.wait('.identity-grid > .identity-stack > .card:first-child [role="alert"]');
  const denied=await page.eval(()=>document.querySelector('.identity-grid > .identity-stack > .card:first-child [role="alert"]').textContent.includes('No consent or evidence was saved'));
  if(!denied)throw new Error('Consent did not explain its canonical request outage');
  await page.open(consent);
  await page.wait('.identity-grid > .identity-stack > .card:nth-child(2) > p:not([role])');
  const empty=await page.eval(()=>document.querySelector('.identity-grid > .identity-stack > .card:nth-child(2)').textContent.includes('No consent has been recorded for your account.')&&!document.querySelector('.consent-records'));
  if(!empty)throw new Error('A canonical request outage manufactured a consent decision');
  await page.open(address('en'));
  await page.wait('.directory-detail > .card form > button:not([disabled])');
}
await page.open(address('en'));
const reset=await page.eval(async()=>{
  const base='/api/web/v1/catalog/v1/options/movement';
  const read=await fetch(`${base}?brand_id=00000000-0011-4000-8000-000000000001`);
  const data=await read.json();
  if(data.sample!==true)throw new Error('Only explicitly sample content belongs in this proof');
  const {id,revision,...definition}=data.items[0];
  if(definition.currency==='USD'&&definition.quote_minor===25000)return true;
  return (await fetch(`${base}/${id}`,{method:'PUT',headers:{'Content-Type':'application/json','Authorization':'Bearer brand','Idempotency-Key':crypto.randomUUID()},
    body:JSON.stringify({...definition,expected_revision:revision,active:true,currency:'USD',quote_minor:25000})})).ok;
});
if(!reset)throw new Error('Sample indicative option could not be restored');
await createBuyer();
await checkConsentOutage();
await page.open(address('en'));
await page.wait('.directory-detail > .card form > button:not([disabled])');
await page.click('.directory-detail > .card form > button:not([disabled])');
await page.wait('.directory-detail > .card form .notice[role="status"]');
// Use trusted key events: programmatic fill can change the DOM without React's state.
await page.click('.movement-panel form > label:last-of-type > input');
// CSS click uses HTMLElement.click(), which does not focus text inputs.
await page.eval(()=>{const input=document.querySelector('.movement-panel form > label:last-of-type > input');input.focus();input.select();});
await page.type('hours, unsupported-chronograph');
await page.click('.movement-panel form > button:not([disabled])');
await page.wait('.movement-snapshot');
const saved=JSON.parse(await page.eval(()=>JSON.stringify({
  manual_review:document.querySelector('.movement-snapshot').textContent.includes('requiring manual review'),
  service_restored:document.querySelector('.directory-restored')!==null,
  snapshot:document.querySelector('.movement-snapshot').textContent,
  functions:document.querySelector('.movement-panel form > label:last-of-type input').value,
})));
if(!saved.manual_review||!saved.service_restored||saved.functions!=='hours, unsupported-chronograph')throw new Error(`Private result mismatch: ${JSON.stringify(saved)}`);
// A fixture-authorized brand changes the public indicative currency; the buyer snapshot must not change.
const updated=await page.eval(async()=>{
  const base='/api/web/v1/catalog/v1/options/movement';
  const read=await fetch(`${base}?brand_id=00000000-0011-4000-8000-000000000001`);
  const option=(await read.json()).items[0];
  const {id,revision,...definition}=option;
  const response=await fetch(`${base}/${id}`,{method:'PUT',headers:{'Content-Type':'application/json','Authorization':'Bearer brand','Idempotency-Key':crypto.randomUUID()},
    body:JSON.stringify({...definition,expected_revision:revision,active:true,currency:'LBP',quote_minor:25000000})});
  return response.ok;
});
if(!updated)throw new Error('Published option revision was not updated');
const cases=[];
for(const locale of ['en','ar'])for(const theme of ['light','dark']){
  await page.open(address(locale));
  await page.wait('.movement-snapshot');
  if(await page.eval(()=>document.documentElement.dataset.theme)!==theme)await page.click('.preferences button');
  await page.eval(()=>document.querySelector('.movement-panel form > button').scrollIntoView({block:'center',behavior:'instant'}));
  const result=JSON.parse(await page.eval(()=>{
    const locale=document.documentElement.lang, language=locale==='ar'?'ar-LB':'en-LB';
    const snapshot=document.querySelector('.movement-snapshot').textContent;
    const current=document.querySelector('.movement-facts').textContent;
    const price=new Intl.NumberFormat(language,{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(250);
    const raw=new Intl.NumberFormat(language,{maximumFractionDigits:0}).format(25000000);
    const button=document.querySelector('.movement-panel form > button'),r=button.getBoundingClientRect(),m=document.querySelector('main').getBoundingClientRect();
    return JSON.stringify({width:innerWidth,locale,theme:document.documentElement.dataset.theme,
      original_units_preserved:snapshot.includes(price),current_units_explicit:current.includes(raw)&&current.includes('LBP'),
      saved_configuration_restored:document.querySelector('.movement-panel form > label:last-of-type input').value==='hours, unsupported-chronograph',
      service_choice_restored:document.querySelector('.directory-restored')!==null,
      stale_revision_explained:document.querySelector('.movement-snapshot [role="status"]')!==null,
      no_horizontal_overflow:document.documentElement.scrollWidth<=innerWidth,
      action_reachable:r.top>=m.top&&r.bottom<=m.bottom&&button.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),
      no_private_cookie_in_script:!document.cookie.includes('bt_refresh=')});
  }));
  if(result.locale!==locale||result.theme!==theme||Object.entries(result).some(([key,value])=>!['width','locale','theme'].includes(key)&&value!==true))throw new Error(JSON.stringify(result));
  cases.push(result);
}
// Revoke the real session outside this page, then let an actual private action discover it.
const loggedOut=await page.eval(async()=>(await fetch('/api/web/v1/identity/v1/accounts/logout',{method:'POST',credentials:'same-origin'})).ok);
if(!loggedOut)throw new Error('Real session could not be revoked');
await page.click('.movement-panel form > button:not([disabled])');
await page.wait('.movement-panel a.button');
const revoked=await page.eval(()=>!document.querySelector('.movement-snapshot')&&!document.querySelector('.directory-restored')&&document.querySelector('.directory-detail > .card form a.button')!==null);
if(!revoked)throw new Error('A revoked real session retained private screen state');
await createBuyer();
await page.open(address('en'));
await page.wait('.movement-panel form > button:not([disabled])');
const isolated=await page.eval(()=>!document.querySelector('.movement-snapshot')&&!document.querySelector('.directory-restored')&&!document.querySelector('.movement-panel form > label:last-of-type input').value.includes('unsupported-chronograph'));
if(!isolated)throw new Error('A different real buyer inherited private state');
console.log(JSON.stringify({cases,cross_buyer_isolation:true,revoked_session_clears_private_state:true,real_registration_and_signin:true,consent_outage_saved_nothing:true,authority:'real Accounts routes; business/staff V1 fixture'}));
