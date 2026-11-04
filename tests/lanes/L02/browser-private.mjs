// Connected BFF/Identity proof. fixture is supplied by the bounded local runner.
const results = [];
const proofEmail = `sample-browser-${fixture.operator_email}`;
const password = fixture.sample_password;
async function api(path, method = 'GET', body, token) {
  const result = await page.eval(`(async () => {
    const response = await fetch('/api/web/v1/identity${path}', {
      method: ${JSON.stringify(method)}, credentials: 'same-origin',
      headers: {'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID(),
        ...${JSON.stringify(token ? {Authorization: `Bearer ${token}`} : {})}},
      ${body === undefined ? '' : `body:JSON.stringify(${JSON.stringify(body)}),`}
    });
    return {status:response.status, body:await response.json()};
  })()`);
  if (result.status >= 400) throw new Error(`${method} ${path}: ${JSON.stringify(result)}`);
  return result.body;
}
async function login(email) {
  await api('/v1/accounts/logout', 'POST');
  await page.open('http://localhost:3202/en/account');
  await page.wait('input[name="email"]');
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', password);
  await page.click('.identity-form button');
  await page.wait('.identity-actions');
  return api('/v1/accounts/refresh', 'POST');
}
async function until(expression, description) {
  for (let attempt = 0; attempt < 80; attempt++) {
    if (await page.eval(expression)) return;
    await page.eval(async () => { await new Promise(resolve => setTimeout(resolve, 100)); return true; });
  }
  throw new Error(description + ': ' + await page.eval('document.querySelector("main")?.innerText'));
}
async function select(selector, value) {
  await page.eval(`(() => {const el=document.querySelector(${JSON.stringify(selector)});el.value=${JSON.stringify(value)};el.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function success() {
  await until(`!![...document.querySelectorAll('.business-feedback[role="status"]')].length`, 'Acknowledged command missing');
  const alert = await page.eval('document.querySelector(".business-feedback[role=alert]")?.innerText');
  if (alert) throw new Error(alert);
}
await page.open('http://localhost:3202/en/account');
await page.wait('input[name="email"]');
await page.click('.identity-tabs button:nth-child(2)');
await page.fill('input[name="display_name"]', 'Sample browser colleague');
await page.fill('input[name="email"]', proofEmail);
await page.fill('input[name="password"]', password);
await page.click('.identity-form button');
await page.wait('.identity-actions');
let buyer = await api('/v1/accounts/refresh', 'POST');
if (buyer.principal.roles.join() !== 'buyer') throw new Error('Buyer registration granted extra privileges');
await page.open('http://localhost:3202/ar/business/contacts');
await page.wait('input[name="recipient"]');
await select('select[name="channel"]', 'phone');
await page.fill('input[name="recipient"]', '+٩٦١٧٠١٢٣٤٥٦');
await page.fill('input[name="reauth"]', password);
await page.click('form:has(input[name="recipient"]) button[type="submit"]');
await page.wait('.business-proof');
await page.click('.business-proof > button');
await until(`!![...document.querySelectorAll('.business-proof bdi')].find(el => /^[0-9]{6}$/.test(el.textContent))`, 'Sample code not displayed');
const code = await page.eval(`[...document.querySelectorAll('.business-proof bdi')].find(el => /^[0-9]{6}$/.test(el.textContent)).textContent`);
await page.fill('input[name="code"]', code.replace(/\d/g, digit => '٠١٢٣٤٥٦٧٨٩'[Number(digit)]));
await page.click('form:has(input[name="code"]) button[type="submit"]');
await until('!document.querySelector(".business-proof")', 'Contact verification did not complete');
let contacts = await api('/v1/contacts', 'GET', undefined, buyer.access_token);
if (contacts.phone !== '+96170123456' || !contacts.phone_verified || !contacts.phone_sample) throw new Error('Contact proof was not persisted/sample labeled');
results.push({story:'contact proof',arabicDigits:true,verified:true,sampleDelivery:true});

const operator = await login(fixture.operator_email);
await page.open('http://localhost:3202/en/business');
await page.wait('input[name="legal_name"]');
await page.fill('input[name="legal_name"]', 'Sample Browser Atelier SAL');
await page.fill('input[name="public_name"]', 'Sample Browser Atelier');
await select('select[name="kind"]', 'brand');
await page.fill('input[name="assurance"]', 'DEMO-private-communication-reference');
await page.click('input[value="customization"]');
await page.click('input[value="servicing"]');
await page.fill('form:has(input[name="legal_name"]) input[name="reason"]', 'Sample brand onboarding recorded after private communication');
await page.click('input[name="sample"]');
await page.click('form:has(input[name="legal_name"]) button[type="submit"]');
await success();
const directory = await api('/v1/businesses');
const business = directory.items.find(item => item.public_name === 'Sample Browser Atelier');
if (!business || !business.sample || business.capabilities.length !== 3 || 'legal_name' in business || 'assurance_reference' in business) throw new Error('Public business boundary failed');
if (await page.eval('document.querySelector("input[name=legal_name]").value') !== '') throw new Error('Acknowledged onboarding form did not clear');
results.push({story:'official brand onboarding',publicPrivateBoundary:true,sample:true,capabilities:business.capabilities});

await page.open('http://localhost:3202/en/business/membership');
await page.wait('input[name="subject"]');
const grant = 'form:has(input[name="subject"])';
await page.fill(grant+' input[name="business"]', business.id);
await page.fill(grant+' input[name="subject"]', buyer.account.id);
await page.fill(grant+' input[name="scope"]', 'Sample stock and staff records only');
await page.fill(grant+' input[name="qualifications"]', 'Sample records training');
await page.click(grant+' input[value="business.stock.write"]');
await page.click(grant+' input[value="business.staff.manage"]');
await page.fill(grant+' input[name="reason"]', 'Sample independent colleague authorized for this organization');
await page.click(grant+' button[type="submit"]');
await success();
buyer = await login(proofEmail);
if (buyer.principal.permissions.includes('identity.listings.publish') || !buyer.principal.organization_grants.some(item => item.organization_id === business.id && item.permissions.includes('identity.listings.publish'))) throw new Error('Organization grant leaked to platform permissions');
await page.open('http://localhost:3202/en/business/membership');
await page.wait('input[name="business"]');
await page.fill('input[name="business"]', business.id);
await page.click('form button[type="submit"]');
await until('document.querySelector("main").innerText.includes("Sample stock and staff records only")', 'Scoped staff read did not render');
if (await page.eval('!!document.querySelector("input[name=subject]")')) throw new Error('Staff member saw operator grant controls');
results.push({story:'scoped colleague membership',organizationOnly:true,staffRead:true,operatorControlsHidden:true});

// Use the owning applicant screen and real synthetic text uploads, not a seeded case.
await page.open('http://localhost:3202/en/seller/verification');
await page.wait('input[name="identity_name"]');
await page.fill('input[name="identity_name"]', 'Sample browser applicant');
await page.fill('input[name="contact"]', proofEmail);
await page.fill('input[name="payout_reference"]', 'DEMO-BROWSER-PAYOUT');
await page.eval(() => {
  for (const name of ['identity_evidence','possession_evidence']) {
    const transfer=new DataTransfer();
    transfer.items.add(new File(['DEMO: synthetic browser '+name+' reference; not physical authentication'],name+'.txt',{type:'text/plain'}));
    const input=document.querySelector(`input[name="${name}"]`);
    input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));
  }
  return true;
});
await page.click('.identity-form button');
await page.wait('.identity-status[data-state="pending"]');
const application = (await api('/v1/private-seller/applications/me','GET',undefined,buyer.access_token)).application;
await login(fixture.operator_email);
await page.open('http://localhost:3202/en/operations/verification');
await page.wait('input[name="application"]');
const assign = 'form:has(input[name="application"])';
await page.fill(assign+' input[name="application"]', application.id);
await page.fill(assign+' input[name="reviewer"]', operator.account.id);
await page.fill(assign+' input[name="reason"]', 'Independent sample applicant review assigned');
await page.click(assign+' button[type="submit"]');
await success();
await page.click('.business-queue button');
await page.wait('input[name="application_revision"]');
await until('document.querySelectorAll(".business-queue li button").length === 3', 'Actual evidence list missing');
await page.eval(`(() => { const el=[...document.querySelectorAll('button')].find(el=>el.textContent==='Download private evidence');if(!el)throw new Error('Evidence action missing');el.click(); })()`);
await select('select[name="state"]', 'approved');
await page.fill('form:has(input[name="application_revision"]) input[name="reason"]', 'Sample identity and possession references checked independently');
await page.click('form:has(input[name="application_revision"]) button[type="submit"]');
await success();
const own = await login(proofEmail);
if (!own.principal.roles.includes('private_seller')) throw new Error('Approved individual grant missing');
await page.open('http://localhost:3202/en/business/review-history');
await until('document.querySelector("main").innerText.includes("Sample identity and possession references checked independently")', 'Applicant reason/history did not render');
results.push({story:'private-seller review',realApplication:true,independentAssignment:true,evidenceActions:true,approved:true,ownerReasonHistory:true});
console.log(JSON.stringify({proof:'private connected interactions',results},null,2));
