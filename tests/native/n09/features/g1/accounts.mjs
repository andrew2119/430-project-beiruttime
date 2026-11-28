import { assert, button, choose, copy, feature, formFor, loseResponse, observe, open, reference, response, result, submit, uploadText, visible } from './browser.mjs';

const password = 'test-password-Beirut-Time-1234';
async function register(ctx) {
  await open(ctx, '/account');
  const t = await copy(ctx, 'identity');
  await button(ctx, t.signout);
  await button(ctx, t.register);
  const name = ctx.uniq('Beirut Time test');
  await ctx.page.fill('[name="display_name"]', name);
  const email = `${ctx.uniq('test')}@example.test`;
  await ctx.page.fill('[name="email"]', email);
  await ctx.page.fill('[name="password"]', password);
  await observe(ctx);
  await submit(ctx);
  const receipt = await response(ctx, '/accounts/register');
  const actor = {actor_id:receipt.json?.account?.id};
  assert.ok(actor.actor_id, 'Registration must return the created account');
  await visible(ctx, name);
  return {actor, receipt, t, email};
}
async function accountJourney(ctx) {
  const {actor, t, email} = await register(ctx);
  await button(ctx,t.signout);
  await ctx.page.fill('[name="email"]',email);
  await ctx.page.fill('[name="password"]',password);
  await observe(ctx); await submit(ctx);
  const signedIn=await response(ctx,'/accounts/login');
  assert.equal(signedIn.json.account.id,actor.actor_id);
  await ctx.page.reload();
  await visible(ctx, t.welcome);
  return result(actor, actor.actor_id);
}
async function accountNegative(ctx) {
  const {actor} = await register(ctx);
  await ctx.page.fill('[name="current_password"]', 'test-wrong-password');
  await ctx.page.fill('[name="new_password"]', 'test-next-password-1234');
  await observe(ctx);
  await formFor(ctx, 'current_password');
  const denied = await response(ctx, '/accounts/password', true);
  assert.equal(denied.json?.code ?? denied.json?.error?.code, 'invalid_credentials');
  return result(actor, reference(denied));
}
async function application(ctx, recovery = false) {
  const {actor, t} = await register(ctx);
  await ctx.page.goto('/seller/verification');
  await ctx.page.waitFor('[name="identity_name"]', {timeout:10000});
  await ctx.page.fill('[name="identity_name"]', 'Beirut Time synthetic seller');
  await ctx.page.fill('[name="contact"]', `${ctx.uniq('test')}@example.test`);
  await ctx.page.fill('[name="payout_reference"]', `DEMO-${ctx.uniq('test').replace(/[^A-Za-z0-9-]/g,'').slice(0,50)}`);
  await uploadText(ctx, 'identity_evidence');
  await uploadText(ctx, 'possession_evidence');
  await observe(ctx);
  await submit(ctx);
  const receipt = await response(ctx, '/private-seller/applications');
  assert.equal(receipt.json.application.status, 'pending');
  const id = receipt.json.application.id;
  await visible(ctx, id);
  await visible(ctx, t.pending);
  if (recovery) { await ctx.page.reload(); await visible(ctx, id); await visible(ctx, t.pending); }
  return result(actor, id);
}
async function privateNegative(ctx) {
  const established = await application(ctx);
  const actor = await open(ctx, '/seller/verification', 'buyer2');
  assert.notEqual(actor.actor_id, established.actor_id);
  assert.ok(!(await ctx.page.text('body')).includes(established.operation_id), 'Another buyer must not see the private case');
  // The ownership check is exercised through the same public gateway as the page.
  const denied = await ctx.api('identity', 'GET', `/v1/private-seller/applications/${established.operation_id}/evidence/${established.operation_id}`, undefined, {as:'buyer2'});
  assert.equal(denied.status,403);
  return result(actor, established.operation_id);
}
async function contact(ctx, mode) {
  const {actor} = await register(ctx);
  await ctx.page.goto('/business/contacts');
  await ctx.page.waitFor('[name="recipient"]', {timeout:10000});
  const recipient = `${ctx.uniq('test-contact')}@example.test`;
  await ctx.page.fill('[name="recipient"]', recipient);
  await ctx.page.fill('[name="reauth"]', password);
  await observe(ctx);
  await formFor(ctx, 'recipient');
  const created = await response(ctx, '/contacts/challenges');
  const challenge = created.json;
  assert.equal(challenge.delivery_mode, 'sample_simulator');
  await ctx.page.waitFor('[name="code"]', {timeout:10000});
  const words=await copy(ctx,'business');
  await button(ctx,words.showCode);
  const code = await response(ctx, `/contacts/challenges/${challenge.id}/sample-code`,false,'GET');
  assert.match(code.json.code, /^\d{6}$/);
  await ctx.page.fill('[name="code"]',mode==='negative' ? (code.json.code==='000000'?'000001':'000000') : code.json.code);
  await observe(ctx);
  if(mode==='recovery') await loseResponse(ctx,`/contacts/challenges/${challenge.id}/verify`);
  await formFor(ctx, 'code');
  const verified = await response(ctx, `/contacts/challenges/${challenge.id}/verify`, mode === 'negative');
  if (mode === 'recovery') {
    await observe(ctx); await formFor(ctx,'code');
    const repeated=await response(ctx,`/contacts/challenges/${challenge.id}/verify`);
    assert.deepEqual(repeated.json,verified.json);
  }
  if (mode !== 'negative') {
    await visible(ctx, recipient);
    if (mode === 'recovery') { await ctx.page.reload(); await visible(ctx, recipient); }
  }
  return result(actor, verified.request_id ?? challenge.id);
}
async function business(ctx, mode) {
  const actor = await open(ctx, '/business', mode === 'negative' ? 'buyer' : 'operator');
  if (mode === 'negative') {
    assert.equal(await ctx.page.exists('[name="legal_name"]'),false);
    const denied = await ctx.api('identity','GET','/v2/businesses/manage/records',undefined,{as:'buyer'});
    assert.ok([401,403].includes(denied.status));
    return result(actor, reference({json:denied.json}));
  }
  const names = [];
  let last;
  for (const kind of ['dealer','brand']) {
    if (last) await ctx.page.goto('/business');
    await ctx.page.waitFor('[name="legal_name"]',{timeout:10000});
    const scope = 'form:has([name="legal_name"])';
    const name = ctx.uniq('Beirut Time test'); names.push(name);
    for (const [key,value] of Object.entries({legal_name:name,public_name:name,assurance:'test-assurance',reason:'test synthetic onboarding'}))
      await ctx.page.fill(`${scope} [name="${key}"]`,value);
    const words=await copy(ctx,'business');
    await choose(ctx,'kind',words[kind],scope);
    await ctx.page.click(`${scope} [name="sample"]`);
    await observe(ctx);
    await formFor(ctx,'legal_name');
    last = await response(ctx,'/businesses');
    assert.equal(last.json.kind,kind);
    assert.equal(last.json.state,'active');
    await visible(ctx,name);
  }
  if (mode === 'recovery') { await ctx.page.reload(); for (const name of names) await visible(ctx,name); }
  return result(actor,reference(last));
}
async function secondFactor(ctx, mode) {
  const {actor, receipt} = await register(ctx);
  // The published factor command supports enroll, confirm and scoped prove.
  // Account login currently returns a session without a factor challenge.
  // Enrollment alone cannot establish the required two-factor login proof.
  const error = new Error(`F5 ${mode}: connected proof deferred until account login composes a second-factor challenge`);
  error.code = 'connected_proof_deferred';
  error.operation_id = reference(receipt);
  error.actor_id = actor.actor_id;
  throw error;
}
async function personalData(ctx, mode) {
  const actor = await open(ctx,'/account/data');
  await observe(ctx);
  if(mode==='recovery') await loseResponse(ctx,'/data-requests');
  await button(ctx,ctx.cell.locale === 'ar' ? 'تقديم الطلب' : 'Submit request');
  const receipt = await response(ctx,'/data-requests');
  const id = reference(receipt);
  if(mode==='recovery') {
    await observe(ctx);
    await button(ctx,ctx.cell.locale === 'ar' ? 'تقديم الطلب' : 'Submit request');
    const repeated=await response(ctx,'/data-requests');
    assert.equal(reference(repeated),id);
    assert.equal(repeated.json.revision,receipt.json.revision);
  }
  await visible(ctx,id);
  if (mode === 'negative') {
    const other = await ctx.actor('buyer2');
    const denied = await ctx.api('identity','GET',`/v1/data-requests/operations/${id}`,undefined,{as:'buyer2'});
    assert.ok([403,404].includes(denied.status));
    await ctx.signIn('buyer2'); await ctx.page.goto('/account/data');
    await ctx.page.waitFor('h1',{timeout:10000});
    assert.ok(!(await ctx.page.text('body')).includes(id));
    return result(other,id);
  }
  if (mode === 'recovery') { await ctx.page.reload(); await visible(ctx,id); }
  return result(actor,id);
}
export const accounts = [
  feature(1,accountJourney,accountNegative,accountJourney),
  feature(2,ctx=>contact(ctx,'journey'),ctx=>contact(ctx,'negative'),ctx=>contact(ctx,'recovery')),
  feature(3,ctx=>application(ctx),privateNegative,ctx=>application(ctx,true)),
  feature(4,ctx=>business(ctx,'journey'),ctx=>business(ctx,'negative'),ctx=>business(ctx,'recovery')),
  feature(5,ctx=>secondFactor(ctx,'journey'),ctx=>secondFactor(ctx,'negative'),ctx=>secondFactor(ctx,'recovery')),
  feature(6,ctx=>personalData(ctx,'journey'),ctx=>personalData(ctx,'negative'),ctx=>personalData(ctx,'recovery')),
];
