import {readFile, writeFile, mkdir, rm} from 'node:fs/promises';
import {resolve, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
import {plan, featureManifest} from '../../../../scripts/native-browser.mjs';
import {browser, context, prepare} from './ctx.mjs';
import {prepareObservation} from '../../../../scripts/native-browser-adapter.mjs';

export const reference = value => typeof value==='string' && /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(value);
export async function loadFeatures() {
  const features=[];
  for(let group=1;group<=4;group++) {
    const url=new URL(`./g${group}/index.mjs`,import.meta.url);
    try {await readFile(url);} catch(error) {if(error.code==='ENOENT')continue;throw error;}
    const module=await import(url.href);
    if(!Array.isArray(module.features))throw new Error('Invalid feature group');
    features.push(...module.features);
  }
  if(new Set(features.map(item=>item.feature_id)).size!==features.length)throw new Error('Duplicate feature');
  return features;
}
export async function writeFeature({runDir,cell,mapping,manifest,revision,feature,ctx,setupError,write=writeFile}) {
  const scenarios={journey:'failed',negative:'failed',recovery:'failed'};
  const record={schema_version:1,boundary:'connected',state:'failed',signed_in:false,...mapping,
    manifest_revision:manifest.revision,cell:cell.key,provider_revision:revision,scenarios};
  const results={};
  let reason;
  for(const scenario of Object.keys(scenarios)) {
    try {
      if(!feature)throw new Error('not built');
      if(feature.proof_id!==mapping.proof_id || feature.proof_revision!==mapping.proof_revision)throw new Error('Proof revision differs');
      if(!ctx)throw setupError ?? new Error('Context unavailable');
      const result=await feature[scenario](ctx);
      if(!reference(result?.operation_id)||!reference(result?.actor_id)||(ctx.isActor && !ctx.isActor(result.actor_id)))throw new Error('Invalid operation reference');
      results[scenario]=result; scenarios[scenario]='passed';
    } catch {reason ??= !feature ? 'not built' : !ctx ? setupError?.message || 'Context unavailable' : 'Scenario failed';}
  }
  if(!reason && reference(revision)) {
    Object.assign(record,{operation_id:results.journey.operation_id,actor_id:results.journey.actor_id,state:'passed',signed_in:true});
  } else record.error=reason ?? 'Provider revision unavailable';
  await write(join(runDir,'n09-evidence',cell.key,`${mapping.feature_id}.json`),JSON.stringify(record,null,2)+'\n',{mode:0o600});
  return record;
}
export async function prerequisites({runDir,cell,revision,ctx,io={readFile,writeFile}}) {
  let ledger, evidence;
  try {ledger=JSON.parse(await io.readFile(join(runDir,'ledger.json'),'utf8'));}catch{}
  try {evidence=JSON.parse(await io.readFile(join(runDir,'contacts-bound-evidence.json'),'utf8'));}catch{}
  const operations=Array.isArray(evidence)?evidence:[];
  let actor,current,negative,recovery;
  try {
    actor=await ctx?.actor('buyer');
    current=await ctx?.api('identity','GET','/v1/contacts',undefined,{as:'buyer'});
    if(current?.status===200) {
      const body={password:['Course','demo','passphrase!'].join('-'),purpose:'contact-change',binding:'email:buyer-a.s1@example.test'};
      negative=await ctx?.api('identity','POST','/v1/accounts/reauthenticate',{...body,purpose:'test-invalid-purpose'},{as:'buyer'});
      if(negative?.status===422)recovery=await ctx?.api('identity','POST','/v1/accounts/reauthenticate',body,{as:'buyer'});
    }
  }catch{}
  let ready=ledger?.schema_version===1 && ledger.state==='ready' && ledger.processes?.length>0;
  if(ready) {
    try {
      for(const process of ledger.processes.filter(item=>!item.finished)) {
        if(!Number.isSafeInteger(process.pid) || process.pid<=0)throw new Error();
        const fields=(await io.readFile(`/proc/${process.pid}/stat`,'utf8')).split(')').at(-1).trim().split(/\s+/);
        if(fields[0]==='Z' || fields[19]!==String(process.start_ticks))throw new Error();
      }
    }catch {ready=false;}
  }
  const results={};
  for(const name of ['N01','N05']) {
    const record={schema_version:1,boundary:'connected',state:'failed',signed_in:false,cell:cell.key,provider_revision:revision,error:'Connected prerequisite unavailable'};
    const bound=operations.filter(item=>item.provider_revision===revision && item.actor_id===actor?.actor_id && reference(item.request_id));
    const walked=bound.some(item=>item.service==='identity' && item.method==='GET' && item.route==='/v1/contacts' && item.status===200);
    const recovered=negative?.status===422 && recovery?.status===200 && reference(negative.operation_id) && reference(recovery.operation_id);
    if(ready && current?.status===200 && reference(current.operation_id) && reference(actor?.actor_id) && reference(revision)
      && (name==='N01' || (walked && recovered))) {
      Object.assign(record,{state:'passed',signed_in:true,operation_id:name==='N05'?recovery.operation_id:current.operation_id,actor_id:actor.actor_id});delete record.error;
      if(name==='N05')record.scenarios={journey:bound.find(item=>item.route==='/v1/contacts' && item.status===200).request_id,negative:negative.operation_id,recovery:recovery.operation_id};
    } else if(name==='N05' && operations.length && !bound.length)record.error='Walkthrough actor and revision binding unavailable';
    results[name]=record;
    await io.writeFile(join(runDir,'n09-evidence',cell.key,`${name}.json`),JSON.stringify(record,null,2)+'\n',{mode:0o600});
  }
  return results;
}
export async function run(options, dependencies={}) {
  const matrix=JSON.parse(await readFile('scripts/native-browser-matrix.json','utf8'));
  const manifest=featureManifest(matrix.feature_manifest);
  if(!manifest)throw new Error('Invalid manifest');
  const selected=options.features?.split(',');
  if(selected?.some(id=>!manifest.features.some(item=>item.feature_id===id)))throw new Error('Unknown feature');
  const cells=plan(matrix).filter(cell=>!options.cells || options.cells==='all' || options.cells.split(',').includes(cell.key));
  if(!cells.length)throw new Error('Unknown cell');
  const features=await (dependencies.loadFeatures ?? loadFeatures)();
  const revision=dependencies.revision ?? execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim();
  let setupError;
  if(features.length)try {await (dependencies.prepare ?? prepare)({...options,revision});}catch(error) {setupError=error;}
  const results=[];
  for(const raw of cells) {
    const cell={...raw,locale:raw.language};
    await mkdir(join(options.runDir,'n09-evidence',cell.key),{recursive:true,mode:0o700});
    for(const name of ['page','observation'])await rm(join(options.runDir,'n09-evidence',cell.key,`${name}.json`),{force:true});
    let session,ctx;
    let cellError=setupError;
    try {
      if(!setupError && features.length) {
        try {
          session=await (dependencies.browser ?? browser)({browserPath:process.env.BT_NATIVE_BROWSER,origin:options.origin,cell});
          await session.page.goto('/');
          ctx=context({page:session.page,origin:options.origin,cell,revision});
        } catch(error) {ctx=undefined;cellError=error;}
      }
      for(const mapping of manifest.features.filter(item=>!selected || selected.includes(item.feature_id))) {
        results.push(await writeFeature({runDir:options.runDir,cell,mapping,manifest,revision,ctx,setupError:cellError,feature:features.find(item=>item.feature_id===mapping.feature_id)}));
      }
      const proofs=await (dependencies.prerequisites ?? prerequisites)({runDir:options.runDir,cell,revision,ctx});
      if(ctx && proofs.N01.state==='passed') {
        const checks=await (dependencies.prepareObservation ?? prepareObservation)(ctx);
        await writeFile(join(options.runDir,'n09-evidence',cell.key,'observation.json'),JSON.stringify({...proofs.N01,checks}),{mode:0o600});
        if(session.detach) {
          await writeFile(join(options.runDir,'n09-evidence',cell.key,'page.json'),JSON.stringify({socket:session.socket,provider_revision:revision,origin:options.origin,cell:cell.key}),{mode:0o600});
          await session.detach();
        }
      }
    } catch(error) {
      for(const record of results.filter(item=>item.cell===cell.key)) {
        record.state='failed';record.error ??= error.message || 'Cell preparation failed';
        await writeFile(join(options.runDir,'n09-evidence',cell.key,`${record.feature_id}.json`),JSON.stringify(record,null,2)+'\n',{mode:0o600});
      }
    } finally {
      try {await session?.close();}
      catch {
        const failed=results.filter(item=>item.cell===cell.key);
        for(const record of failed) {
          record.state='failed';record.error ??= 'Session cleanup failed';record.cleanup='failed';
          await writeFile(join(options.runDir,'n09-evidence',cell.key,`${record.feature_id}.json`),JSON.stringify(record,null,2)+'\n',{mode:0o600});
        }
      }
    }
  }
  return results;
}
export function parse(args) {
  const options={};
  for(let i=0;i<args.length;i++) {
    if(!['--origin','--run-dir','--features','--cells'].includes(args[i]) || !args[i+1] || args[i+1].startsWith('--'))throw new Error('Invalid argument');
    options[args[i].slice(2).replace('run-dir','runDir')]=args[++i];
  }
  const url=new URL(options.origin);
  if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.pathname!=='/'||url.search||url.hash||!options.runDir)throw new Error('Origin and run directory required');
  options.origin=url.origin;options.runDir=resolve(options.runDir);return options;
}
if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href) {
  run(parse(process.argv.slice(2))).then(results=>{if(results.some(item=>item.state!=='passed'))process.exitCode=1;}).catch(()=>{console.error('Feature proof run failed');process.exitCode=1;});
}
