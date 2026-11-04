// Real gateway + domain HTTP + PostgreSQL, with the explicitly labeled Identity V1 fixture.
await page.open('http://127.0.0.1:3111/en/services');
await page.wait('.directory-business');
const proof=await page.eval(async()=>{
  const directory='/api/web/v1/service-operations/v1/directory';
  const movement='/api/web/v1/catalog/v1/options/movement';
  async function invoke(path,token,method='GET',body,key){
    const response=await fetch(path,{method,headers:{Authorization:`Bearer ${token}`,...(body?{'Content-Type':'application/json','Idempotency-Key':key}:{})},...(body?{body:JSON.stringify(body)}:{})});
    return {status:response.status,body:await response.json()};
  }
  const businesses=await invoke(`${directory}/businesses`,'buyer');
  if(businesses.status!==200||businesses.body.items.length!==1)throw new Error('No canonical directory content');
  const business=businesses.body.items[0];
  const choice={organization_id:business.organization_id,capability:'maintenance',purpose:'servicing',expected_revision:0,profile_revision:business.revision};
  const key=crypto.randomUUID();
  const first=await invoke(`${directory}/choices`,'buyer','POST',choice,key);
  const replay=await invoke(`${directory}/choices`,'buyer','POST',choice,key);
  const conflict=await invoke(`${directory}/choices`,'buyer','POST',{...choice,capability:'repair'},key);
  const own=await invoke(`${directory}/choices/current`,'buyer');
  const other=await invoke(`${directory}/choices/current`,'other');
  if(first.status!==200||replay.status!==200||first.body.id!==replay.body.id||first.body.revision!==replay.body.revision||conflict.status!==409||own.body.choice.revision!==1||other.body.choice!==null)throw new Error('Directory gateway scope/replay failed');
  const options=await invoke(`${movement}?brand_id=${business.organization_id}`,'buyer');
  const option=options.body.items[0];
  const selection={brand_id:business.organization_id,option_id:option.id,option_revision:option.revision,expected_revision:0,
    configuration:{case:option.cases[0],dial:option.dials[0],hands:option.hands[0],functions:option.functions}};
  const supported=await invoke(`${movement}/selections`,'buyer','POST',selection,crypto.randomUUID());
  const manual=await invoke(`${movement}/selections`,'buyer','POST',{...selection,expected_revision:1,configuration:{...selection.configuration,functions:['unsupported-chronograph']}},crypto.randomUUID());
  const saved=await invoke(`${movement}/selections/current?brand_id=${business.organization_id}`,'buyer');
  const stranger=await invoke(`${movement}/selections/current?brand_id=${business.organization_id}`,'other');
  if(supported.status!==200||supported.body.status!=='supported_for_review'||manual.status!==200||manual.body.status!=='manual_review'||manual.body.physical_feasibility_pass!==false||saved.body.selection.revision!==2||stranger.body.selection!==null)throw new Error('Movement gateway privacy/review failed');
  return JSON.stringify({directory_persisted:true,scope_private:true,idempotency_replayed:true,key_conflict_refused:true,movement_supported_for_review:true,unsupported_saved_for_manual_review:true,no_physical_pass:true,movement_restored:true});
});
console.log(proof);
