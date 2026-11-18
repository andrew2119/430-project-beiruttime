import {readFile} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {connectSession} from '../tests/native/n09/features/ctx.mjs';
import {cases, featureCoverage, validate} from './native-browser.mjs';

const reference=value=>typeof value==='string' && /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(value);
export function runDirectory(args=process.argv.slice(2)) {
  const index=args.indexOf('--run-dir');
  if(index<0 || !args[index+1])throw new Error('Evidence directory required');
  return resolve(args[index+1]);
}
export async function measure(page,cell) {
  await page.press('Tab');
  const result=await page.evaluate(() => {
    const root=document.querySelector('.bt-shell') ?? document.documentElement;
    const visible=el=>{const r=el.getBoundingClientRect();return r.width>0 && r.height>0 && getComputedStyle(el).visibility!=='hidden';};
    const controls=[...document.querySelectorAll('button,a[href],input,select,textarea,[role="button"]')].filter(visible);
    const inputs=controls.filter(el=>el.matches('input,select,textarea'));
    const focus=document.activeElement;
    const rect=focus?.getBoundingClientRect();
    const rail=document.querySelector('.bt-shell-rail');const railRect=rail?.getBoundingClientRect();
    const direction=getComputedStyle(root).direction;
    const focused=focus!==document.body && !!rect?.width && getComputedStyle(focus).outlineStyle!=='none';
    return {metrics:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio,mobile:matchMedia('(pointer:coarse)').matches,
      touch:navigator.maxTouchPoints>0,language:root.lang || document.documentElement.lang,direction,
      theme:document.documentElement.dataset.theme || (document.documentElement.classList.contains('dark')?'dark':matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light')},
      checks:{keyboard:focused,focus:focused,reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches,
        longArabic:direction==='rtl' && /[\u0600-\u06ff]{3}/.test(root.textContent) && root.textContent.length>120,
        overflow:document.documentElement.scrollWidth<=innerWidth,
        safeAreas:controls.length>0 && controls.every(el=>{const r=el.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth;}),
        touchFloor:controls.length>0 && controls.every(el=>{const r=el.getBoundingClientRect();return r.width>=44 && r.height>=44;}),
        inputFloor:inputs.length>0 && inputs.every(el=>parseFloat(getComputedStyle(el).fontSize)>=16),
        oppositeSidebar:railRect?direction==='rtl'?railRect.left>=innerWidth/2:railRect.right<=innerWidth/2:matchMedia('(max-width: 767px)').matches}};
  });
  const initial=await localeChecks(page,cell,{privateState:false});
  initial.longArabic ||= result.checks.longArabic;
  Object.assign(result.checks,initial);
  Object.assign(result.checks,await dialogChecks(page));
  for(const name of cases) result.checks[name] ??= false;
  return result;
}
export async function dialogChecks(page) {
  const original=await page.url();
  let navigated=false;
  const select=()=>page.evaluate(()=>{
    const trigger=[...document.querySelectorAll('button[aria-haspopup="dialog"]')].find(el=>{
      const rect=el.getBoundingClientRect(),style=getComputedStyle(el);
      return rect.width>0 && rect.height>0 && style.visibility==='visible' && style.display!=='none'
        && !el.matches(':disabled') && el.getAttribute('aria-disabled')!=='true' && !el.closest('[inert]');
    });
    if(!trigger)return false;
    trigger.setAttribute('data-n09-dialog-trigger','');
    window.__btN09Invoker=trigger;
    trigger.focus();
    return true;
  });
  try {
    if(!await select()) {
      navigated=true;
      await page.goto('/business/contacts');
      await page.waitFor('button[role="combobox"][aria-haspopup="dialog"]:enabled');
      if(!await select())return {dialog:false,escape:false};
    }
    await page.click('[data-n09-dialog-trigger]');
    await page.waitFor('[role="dialog"]');
    let contained=true;
    for(let i=0;i<12;i++) {
      await page.press('Tab');
      contained &&= await page.evaluate(()=>!!document.querySelector('[role="dialog"]')?.contains(document.activeElement));
    }
    await page.press('Escape');
    const restored=await page.evaluate(()=>document.activeElement===window.__btN09Invoker && !document.querySelector('[role="dialog"]'));
    return {dialog:contained,escape:restored};
  } finally {
    await page.evaluate(()=>{window.__btN09Invoker?.removeAttribute('data-n09-dialog-trigger');delete window.__btN09Invoker;});
    if(navigated)await page.goto(original);
  }
}
export async function prepareLiveObservation(ctx) {
  await ctx.signIn('buyer');
  const {page}=ctx;
  await page.goto('/business/contacts?observation=contact');
  await page.waitFor('input[name="reauth"]:enabled');
  await page.fill('input[name="recipient"]','synthetic-invalid-contact');
  await page.fill('input[name="reauth"]',['Course','demo','passphrase!'].join('-'));
  await page.click('form:has(input[name="reauth"]) button[type="submit"]');
  await page.waitFor('[role="alert"] bdi');
  const operation=await page.text('[role="alert"] bdi');
  if(!reference(operation))throw new Error('Observation request reference unavailable');
  await page.waitFor('input[name="reauth"]:enabled');
  await page.fill('input[name="reauth"]',`synthetic-private-${crypto.randomUUID()}`);
  return operation;
}
export async function prepareObservation(ctx) {
  const {page,cell}=ctx;
  await ctx.signIn('buyer');
  const privateChecks={};
  for(const kind of ['password','file']) {
    await populatePrivateForm(page,kind);
    const checks=await localeChecks(page,cell);
    const name=kind==='password'?'passwordMemoryOnly':'privateFilesMemoryOnly';
    privateChecks[name]=checks[name]===true;
    for(const invariant of ['sameMountedInputs','sameQuery','noLanguageWrites'])
      privateChecks[invariant]=(privateChecks[invariant] ?? true) && checks[invariant]===true;
  }
  await prepareLiveObservation(ctx);
  const result=await localeChecks(page,cell);
  for(const name of ['sameMountedInputs','sameQuery','noLanguageWrites'])result[name] &&= privateChecks[name]===true;
  return {...result,passwordMemoryOnly:privateChecks.passwordMemoryOnly,privateFilesMemoryOnly:privateChecks.privateFilesMemoryOnly};
}
export async function localeChecks(page,cell,{privateState=true}={}) {
  const checks={};
  const snapshot=await page.evaluate(()=>{
    const fields=[...document.querySelectorAll('input,textarea,select')];
    window.__btN09={fields,values:fields.map(el=>el.value),files:fields.map(el=>[...(el.files??[])]),query:location.search,
      operations:[...document.querySelectorAll('bdi')].map(el=>el.textContent.trim()).filter(value=>
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)),writes:0};
    const original=window.fetch;
    window.__btN09.restore=()=>{window.fetch=original;};
    window.fetch=function(input,options){const method=options?.method ?? (input instanceof Request?input.method:'GET');if(!['GET','HEAD','OPTIONS'].includes(method.toUpperCase()))window.__btN09.writes++;return original.apply(this,arguments);};
    return {password:fields.some(el=>el.type==='password' && el.value),files:fields.some(el=>el.files?.length)};
  });
  try {
    if(await page.exists('.bt-locale-control')) {
      await page.click('.bt-locale-control');
      await page.waitFor(`.bt-shell[lang="${cell.language==='ar'?'en':'ar'}"]`);
      const arabic=await page.evaluate(()=>{const root=document.querySelector('.bt-shell');return root?.lang==='ar' && /[\u0600-\u06ff]{3}/.test(root.textContent) && root.textContent.length>120;});
      checks.longArabic = arabic;
      await page.click('.bt-locale-control');await page.waitFor(`.bt-shell[lang="${cell.language}"]`);
      Object.assign(checks,await page.evaluate(async privateState=>{
        const s=window.__btN09;
        const same=s.fields.length>0 && s.fields.every((el,i)=>el.isConnected && el.value===s.values[i]);
        const privateValues=s.fields.filter(el=>el.type==='password').map(el=>el.value).filter(Boolean);
        const storage=JSON.stringify({...localStorage,...sessionStorage})+document.cookie;
        const secrets=[...privateValues,...await Promise.all(s.files.flat().map(file=>file.text()))].filter(Boolean);
        let retained=secrets.some(value=>storage.includes(value));
        if(privateState && secrets.length && 'caches' in window)for(const name of await caches.keys()){const cache=await caches.open(name);for(const request of await cache.keys()){const response=await cache.match(request);if(response){const text=await response.text();retained ||= secrets.some(value=>text.includes(value));}}}
        return {sameMountedInputs:same,sameQuery:location.search===s.query,
          sameOperation:s.operations.length>0 && s.operations.every(value=>
            [...document.querySelectorAll('bdi')].some(el=>el.textContent.trim()===value)),
          noLanguageWrites:s.writes===0,passwordMemoryOnly:same && privateValues.length>0 && !retained,
          privateFilesMemoryOnly:same && !retained && s.fields.every((el,i)=>s.files[i].every((file,j)=>el.files?.[j]===file))};
      },privateState));
      checks.passwordMemoryOnly &&= snapshot.password;
      checks.privateFilesMemoryOnly &&= snapshot.files;
    }
  } finally {await page.evaluate(()=>{window.__btN09?.restore();delete window.__btN09;});}
  return checks;
}
export async function populatePrivateForm(page,kind) {
  if(kind==='password') {
    await page.goto('/business/contacts');
    await page.waitFor('input[name="reauth"]:enabled');
    await page.fill('input[name="reauth"]',`synthetic-private-${crypto.randomUUID()}`);
  } else if(kind==='file') {
    await page.goto('/seller/verification');
    await page.waitFor('input[name="identity_evidence"]:enabled');
    await page.evaluate(()=>{
      const input=document.querySelector('input[name="identity_evidence"]');
      const transfer=new DataTransfer();
      transfer.items.add(new File([`synthetic-private-${crypto.randomUUID()}`],'synthetic-proof.txt',{type:'text/plain'}));
      input.files=transfer.files;
      input.dispatchEvent(new Event('change',{bubbles:true}));
    });
  } else throw new Error('Unknown private form');
}
export async function observe({page,cell,runDir,revision,request,read=readFile,measurePage=measure}) {
  request.signal?.throwIfAborted();
  if(request.schema_version!==1 || JSON.stringify(request.cases)!==JSON.stringify(cases))throw new Error('Invalid observation request');
  const readRecord=async name=> {
    try {
      const record=JSON.parse(await read(join(runDir,'n09-evidence',cell.key,`${name}.json`),'utf8'));
      if(record.schema_version!==1 || record.error || record.boundary!=='connected' || record.state!=='passed' || record.signed_in!==true || record.cell!==cell.key || record.provider_revision!==revision || !['operation_id','actor_id','provider_revision'].every(key=>reference(record[key])))throw new Error();
      return record;
    } catch {throw new Error('Connected evidence unavailable');}
  };
  const proofs={},feature_proofs={};
  for(const name of request.requiredProofs) {if(!['N01','N05'].includes(name))throw new Error('Unknown prerequisite');proofs[name]=await readRecord(name);}
  if(!request.featureManifest)throw new Error('Feature manifest required');
  for(const mapping of request.featureManifest.features)feature_proofs[mapping.feature_id]=await readRecord(mapping.feature_id);
  const prepared=await readRecord('observation');
  const measured=await measurePage(page,cell);
  for(const name of ['passwordMemoryOnly','privateFilesMemoryOnly'])measured.checks[name]=prepared.checks?.[name]===true;
  for(const name of ['sameMountedInputs','sameQuery','noLanguageWrites'])measured.checks[name] &&= prepared.checks?.[name]===true;
  measured.checks.longArabic ||= prepared.checks?.longArabic===true;
  const result={status:'passed',proofs,feature_proofs,...measured};
  featureCoverage(result,request.featureManifest,cell);validate(result,cell);
  request.signal?.throwIfAborted();return result;
}
export async function open(config) {
  if(config.sandbox!==true || config.download!==false || config.reducedMotion!=='reduce')throw new Error('Invalid browser configuration');
  const runDir=runDirectory();
  const revision=execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
  const location=JSON.parse(await readFile(join(runDir,'n09-evidence',config.cell.key,'page.json'),'utf8'));
  if(location.provider_revision!==revision || location.origin!==config.origin || location.cell!==config.cell.key)throw new Error('Prepared session differs');
  const session=await connectSession(location.socket,{signal:config.signal});
  return {close:()=>session.close(),
    observe:request=>observe({page:session.page,cell:config.cell,runDir,revision,request,measurePage:measure}),
    async screenshot(path,{signal}={}) {signal?.throwIfAborted();await session.page.evaluate(()=>{for(const el of document.querySelectorAll('input[type="password"],input[type="file"],[data-private]'))el.style.visibility='hidden';});await session.screenshot(path);signal?.throwIfAborted();},
  };
}
