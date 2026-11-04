// Run with chrome-devtools-axi run < this file in a fresh named browser session.
// Real Identity form + real private draft API; no credential or note is emitted.
async function ref(pattern) {
  const match = pattern.exec(await page.snapshot());
  if (!match) throw Error('Required visible action missing');
  return '@' + match[1];
}
const origin = await page.eval(() => location.origin);
if (!/^http:\/\/(localhost|127\.0\.0\.1):\d+$/.test(origin)) throw Error('Local proof origin required');
await page.open(origin + '/en/account?next=%2Fcustom-requests');
await page.click(await ref(/uid=(\S+) button "Create an account"/));
const suffix = Date.now().toString(36);
await page.fill(await ref(/uid=(\S+) textbox "Your name"/), 'Sample L08 private buyer');
await page.fill(await ref(/uid=(\S+) textbox "Email address"/), 'l08-proof-' + suffix + '@example.test');
await page.fill(await ref(/uid=(\S+) textbox "Password/), 'Sample-private-' + suffix + '!');
await page.click(await ref(/uid=(\S+) button "Continue"/));
await page.wait('input[name=watch_reference]');
await page.fill(await ref(/uid=(\S+) textbox "Watch and reference"/), 'Sample L08 current draft');
await page.fill(await ref(/uid=(\S+) textbox "Scope intent"/), 'Assessment only; no work approval');
await page.fill(await ref(/uid=(\S+) textbox "Private neutral notes/), 'Sample persisted neutral notes');
await page.click(await ref(/uid=(\S+) button "Save private draft"/));
await page.wait(800);
const saved = await page.eval(() => ({id: new URL(location.href).searchParams.get('draft'), notes: document.querySelector('textarea[name=notes]')?.value}));
if (!saved.id || saved.notes !== 'Sample persisted neutral notes') throw Error('Draft acknowledgement missing');
await page.fill(await ref(/uid=(\S+) textbox "Private neutral notes/), 'Sample bilingual current notes');
await page.click(await ref(/uid=(\S+) link "العربية"/));
await page.wait('textarea[name=notes]'); await page.wait(800);
const restored = await page.eval(() => ({id: new URL(location.href).searchParams.get('draft'), notes: document.querySelector('textarea[name=notes]')?.value, lang: document.documentElement.lang}));
if (restored.id !== saved.id || restored.notes !== 'Sample bilingual current notes' || restored.lang !== 'ar') throw Error('Locale save was not acknowledged');
console.log(JSON.stringify({draftId:saved.id,realSignInForm:true,localeAutoSave:true,fullSliceAccepted:false}));
