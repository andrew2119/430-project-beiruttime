// Finish the real private-draft proof with current-server denials and an actual profile switch.
async function ref(pattern) {
  const match=pattern.exec(await page.snapshot());
  if(!match)throw Error('Required visible account action missing');
  return '@'+match[1];
}
const current=await page.eval(()=>({origin:location.origin,id:new URL(location.href).searchParams.get('draft')}));
if(!current.id)throw Error('Acknowledged owner draft required');
const before=await page.eval(async()=>{
  const response=await fetch('/api/web/v1/identity/v1/accounts/refresh',{method:'POST'});
  const session=await response.json();if(response.status!==200)throw Error('Real session unavailable');
  const id=new URL(location.href).searchParams.get('draft');
  const headers={Authorization:'Bearer '+session.access_token};
  const owned=await fetch('/api/web/v1/catalog/v1/request-drafts/'+id,{headers});const draft=await owned.json();
  if(owned.status!==200||draft.revision!==2||draft.approved!==false||draft.payment_authority!==false||draft.notes!=='Sample bilingual current notes')throw Error('Owner acknowledgement mismatch');
  const denials=[];
  for(const action of ['submit','approve','pay','start','complete','collect']) {
    const denied=await fetch('/api/web/v1/catalog/v1/request-drafts/'+id+'/actions/'+action,{method:'POST',headers:{...headers,'Idempotency-Key':crypto.randomUUID()}});
    const error=await denied.json();
    if(denied.status!==409||error.error?.code!=='capability_unreleased')throw Error('Unreleased action was not denied');
    denials.push({action,status:denied.status});
  }
  const storage=[...Object.values(localStorage),...Object.values(sessionStorage)].join(' ');
  if(storage.includes('Sample bilingual current notes')||storage.includes('Bearer '))throw Error('Private browser persistence');
  return {ownerRevision:draft.revision,denials,noPrivateBrowserStorage:true};
});
await page.open(current.origin+'/en/account?next=%2Fcustom-requests');await page.wait(500);
await page.click(await ref(/uid=(\S+) button "Sign out"/));await page.wait(400);
await page.click(await ref(/uid=(\S+) button "Create an account"/));
const suffix=Date.now().toString(36);
await page.fill(await ref(/uid=(\S+) textbox "Your name"/),'Sample L08 second buyer');
await page.fill(await ref(/uid=(\S+) textbox "Email address"/),'l08-second-'+suffix+'@example.test');
await page.fill(await ref(/uid=(\S+) textbox "Password/),'Sample-private-'+suffix+'!');
await page.click(await ref(/uid=(\S+) button "Continue"/));await page.wait('input[name=watch_reference]');
// Transport-only credential never leaves the browser's short-lived request closure.
const foreign=await page.eval(`async () => {
  const refresh=await fetch('/api/web/v1/identity/v1/accounts/refresh',{method:'POST'});const session=await refresh.json();
  if(refresh.status!==200)throw Error('Second real session unavailable');
  const response=await fetch('/api/web/v1/catalog/v1/request-drafts/${encodeURIComponent(current.id)}',{headers:{Authorization:'Bearer '+session.access_token}});
  return {status:response.status,privateDataAbsent:!(await response.text()).includes('Sample bilingual current notes')};
}`);
if(foreign.status!==404||!foreign.privateDataAbsent)throw Error('Foreign owner disclosure');
await page.open(`${current.origin}/en/custom-requests?draft=${encodeURIComponent(current.id)}`);await page.wait(700);
const ui=await page.eval(()=>({formHidden:!document.querySelector('textarea[name=notes]'),priorNotesAbsent:!document.body.textContent.includes('Sample bilingual current notes')}));
if(!ui.formHidden||!ui.priorNotesAbsent)throw Error('Prior owner form survived profile switch');
console.log(JSON.stringify({...before,foreignOwnerStatus:foreign.status,...ui,realIdentity:true,fullSliceAccepted:false}));
