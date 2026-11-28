import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {observe,runDirectory,localeChecks,populatePrivateForm} from '../../../../scripts/native-browser-adapter.mjs';
import {plan,cases,featureManifest} from '../../../../scripts/native-browser.mjs';
import {writeFeature,run,prerequisites} from '../features/run.mjs';

const matrix=JSON.parse(await readFile('scripts/native-browser-matrix.json','utf8'));
const manifest=featureManifest(matrix.feature_manifest),cell=plan(matrix)[0];
const revision='test-revision';
function record(mapping={}) {return {schema_version:1,boundary:'connected',state:'passed',signed_in:true,cell:cell.key,provider_revision:revision,actor_id:'test-actor',operation_id:'test-operation',manifest_revision:manifest.revision,scenarios:{journey:'passed',negative:'passed',recovery:'passed'},...mapping};}
function setup(change=()=>{}) {
  const records={observation:record({checks:Object.fromEntries(cases.map(name=>[name,true]))}),N01:record(),N05:record(),...Object.fromEntries(manifest.features.map(mapping=>[mapping.feature_id,record(mapping)]))};
  change(records);
  return {cell,revision,runDir:'test-output',page:{},request:{schema_version:1,cases,requiredProofs:['N01','N05'],featureManifest:manifest},
    read:async path=>JSON.stringify(records[path.split('/').at(-1).replace('.json','')]),
    measurePage:async()=>({metrics:{...cell,direction:'ltr'},checks:Object.fromEntries(cases.map(name=>[name,true]))})};
}
test('matrix declares eight cells and exact sixty-four mappings',()=>{
  assert.equal(plan(matrix).length,8);assert.equal(manifest.revision,'n09-features-1');
  assert.deepEqual(manifest.features,Array.from({length:64},(_,index)=>({feature_id:`F${index+1}`,proof_id:`f${String(index+1).padStart(2,'0')}-proof`,proof_revision:'1'})));
  assert.equal(matrix.physical_device_record,null);
});
test('observation reads evidence and measures the page',async()=>{
  const options=setup();let measured=false;
  const original=options.measurePage;options.measurePage=async page=>{assert.equal(page,options.page);measured=true;return original();};
  const result=await observe(options);assert.equal(measured,true);assert.equal(result.status,'passed');assert.equal(Object.keys(result.feature_proofs).length,64);
});
test('stale, missing, failed, unsigned and mismatched evidence is refused',async()=>{
  for(const change of [r=>delete r.observation,r=>r.observation.checks.passwordMemoryOnly=false,r=>r.observation.provider_revision='test-stale',r=>delete r.F1,r=>r.F1.provider_revision='old-test-revision',r=>r.N01.signed_in=false,r=>r.F1.scenarios.negative='failed',r=>r.F1.proof_revision='2',r=>r.F1.cell='phone-ar-dark',r=>r.N05.error='test-error'])await assert.rejects(observe(setup(change)));
});
test('a live metric or check failure cannot be replaced by passing evidence',async()=>{
  const options=setup();options.measurePage=async()=>({metrics:{...cell,direction:'ltr'},checks:{}});
  await assert.rejects(observe(options));
});
test('cancellation refuses observation before reading records',async()=>{
  const options=setup();options.request.signal=AbortSignal.abort();options.read=()=>assert.fail('Unexpected read');await assert.rejects(observe(options));
});
test('run directory uses the driver argument',()=>{assert.ok(runDirectory(['--run-dir','test-output']).endsWith('/test-output'));assert.throws(()=>runDirectory([]));});
async function temporary(fn) {const dir=await mkdtemp(join(tmpdir(),'bt-n09-test-'));try {await fn(dir);}finally {await rm(dir,{recursive:true,force:true});}}
test('runner records all three real scenario references and missing groups fail',async()=>temporary(async runDir=>{
  await mkdir(join(runDir,'n09-evidence',cell.key),{recursive:true});
  const seen=[];const feature={...manifest.features[0],...Object.fromEntries(['journey','negative','recovery'].map(name=>[name,async ctx=>{assert.equal(ctx.test,true);seen.push(name);return {operation_id:`test-${name}`,actor_id:'test-actor'};}]))};
  const options={runDir,cell,mapping:manifest.features[0],manifest,revision,ctx:{test:true},feature};
  const result=await writeFeature(options);assert.equal(result.state,'passed');assert.deepEqual(seen,['journey','negative','recovery']);
  const saved=JSON.parse(await readFile(join(runDir,'n09-evidence',cell.key,'F1.json'),'utf8'));assert.equal(saved.operation_id,'test-journey');
  const missing=await writeFeature({...options,feature:undefined});assert.equal(missing.error,'not built');assert.equal(missing.signed_in,false);
}));
test('scenario errors are redacted and subsequent scenarios still run',async()=>temporary(async runDir=>{
  await mkdir(join(runDir,'n09-evidence',cell.key),{recursive:true});let recovered=false;
  const result=await writeFeature({runDir,cell,mapping:manifest.features[0],manifest,revision,ctx:{},feature:{...manifest.features[0],journey:async()=>{throw Error('test-private-detail');},negative:async()=>({operation_id:'test-denied',actor_id:'test-actor'}),recovery:async()=>{recovered=true;return {operation_id:'test-retry',actor_id:'test-actor'};}}});
  assert.equal(recovered,true);assert.equal(result.state,'failed');assert.equal(result.scenarios.negative,'passed');assert.ok(!JSON.stringify(result).includes('test-private-detail'));
}));
test('missing modules produce selected failed records without starting a browser',async()=>temporary(async runDir=>{
  const results=await run({origin:'http://localhost:3000',runDir,features:'F1,F64',cells:cell.key},{loadFeatures:async()=>[],revision,browser:()=>assert.fail('Unexpected browser')});
  assert.equal(results.length,2);assert.ok(results.every(result=>result.error==='not built'));
  for(const name of ['N01','N05'])assert.equal(JSON.parse(await readFile(join(runDir,'n09-evidence',cell.key,`${name}.json`),'utf8')).state,'failed');
}));
test('a ledger alone cannot manufacture connected prerequisites',async()=>{
  const writes=[];const result=await prerequisites({runDir:'test-output',cell,revision,io:{readFile:async()=>JSON.stringify({schema_version:1,state:'ready',processes:[{pid:123}]}),writeFile:async(...args)=>writes.push(args)}});
  assert.equal(result.N01.state,'failed');assert.equal(result.N05.state,'failed');assert.equal(writes.length,2);
});

test('context keeps tokens in memory and switches the actual page session',async()=>{
  const {context}=await import('../features/ctx.mjs');const calls=[];let reloads=0;
  const page={reload:async()=>{reloads++;},evaluate:async(fn,args)=>{
    calls.push(args);
    if(args.path==='/v1/accounts/login')return {status:200,json:{account:{id:`test-${args.body.email}`,display_name:'Test buyer'},access_token:'test-memory-token'}};
    return {status:403,json:{code:'test-refused'}};
  }};
  const ctx=context({page,origin:'http://localhost:3000',cell,revision});
  const buyer=await ctx.actor('buyer');assert.ok(ctx.isActor(buyer.actor_id));assert.equal(ctx.signedInRole(),'buyer');
  assert.equal('token' in buyer,false);assert.equal(reloads,1);
  const result=await ctx.api('identity','POST','/v2/test-record',{}, {as:'buyer'});
  assert.equal(result.status,403);assert.equal(calls.at(-1).token,'test-memory-token');
  await ctx.actor('buyer2');await ctx.actor('buyer');assert.equal(reloads,3);
  await assert.rejects(ctx.api('identity','GET','//example.test/test'));
  await assert.rejects(ctx.signIn('unknown'));
});
test('invalid scenario identities and unavailable browser setup produce failed records',async()=>temporary(async runDir=>{
  await mkdir(join(runDir,'n09-evidence',cell.key),{recursive:true});
  const feature={...manifest.features[0],...Object.fromEntries(['journey','negative','recovery'].map(name=>[name,async()=>({actor_id:'test-unrecognized',operation_id:'test-operation'})]))};
  const result=await writeFeature({runDir,cell,mapping:manifest.features[0],manifest,revision,feature,ctx:{isActor:()=>false}});
  assert.equal(result.state,'failed');assert.equal(result.signed_in,false);
  const results=await run({origin:'http://localhost:3000',runDir,features:'F1',cells:cell.key},{loadFeatures:async()=>[feature],revision,prepare:async()=>{},browser:async()=>{throw Error('test-launch-failed');}});
  assert.equal(results[0].state,'failed');assert.equal(results[0].error,'test-launch-failed');
}));

test('prerequisites bind current authority, live processes and walkthrough scenarios',async()=>{
  const writes=[];const fields=Array(20).fill('0');fields[0]='S';fields[19]='456';
  const rows=[{service:'identity',method:'GET',route:'/v1/contacts',status:403,request_id:'test-refused',actor_id:'test-actor',provider_revision:revision},{service:'identity',method:'GET',route:'/v1/contacts',status:200,request_id:'test-recovered',actor_id:'test-actor',provider_revision:revision}];
  const ctx={actor:async()=>({actor_id:'test-actor'}),api:async(service,method,path,body)=>({status:body?.purpose==='test-invalid-purpose'?422:200,operation_id:body?'test-'+body.purpose:'test-current-request'})};
  const io={readFile:async path=>path.endsWith('ledger.json')?JSON.stringify({schema_version:1,state:'ready',processes:[{pid:123,start_ticks:'456'}]}):path.startsWith('/proc/')?`123 (test process) ${fields.join(' ')}`:JSON.stringify(rows),writeFile:async(...args)=>writes.push(args)};
  const records=await prerequisites({runDir:'test-output',cell,revision,ctx,io});
  assert.equal(records.N01.state,'passed');assert.equal(records.N05.state,'passed');assert.equal(records.N01.operation_id,'test-current-request');
  rows.forEach(row=>delete row.provider_revision);
  const unbound=await prerequisites({runDir:'test-output',cell,revision,ctx,io});
  assert.equal(unbound.N01.state,'passed');assert.equal(unbound.N05.state,'failed');assert.equal(unbound.N05.error,'Walkthrough actor and revision binding unavailable');
});
test('scenario return data cannot overwrite the record contract or persist private fields',async()=>temporary(async runDir=>{
  await mkdir(join(runDir,'n09-evidence',cell.key),{recursive:true});
  const scenario=async()=>({operation_id:'test-operation',actor_id:'test-actor',provider_revision:'test-stale',private_value:'test-private'});
  const feature={...manifest.features[0],journey:scenario,negative:scenario,recovery:scenario};
  const result=await writeFeature({runDir,cell,mapping:manifest.features[0],manifest,revision,ctx:{},feature});
  assert.equal(result.provider_revision,revision);assert.equal('private_value' in result,false);
}));

test('preparation uses callable phases and binds phase evidence at request time',async()=>temporary(async runDir=>{
  const {preparationProgram,prepare}=await import('../features/ctx.mjs');
  const {writeFile}=await import('node:fs/promises');
  const {spawn}=await import('node:child_process');
  const {EventEmitter}=await import('node:events');
  await writeFile(join(runDir,'connected_walkthrough.py'),`
class Walkthrough:
    def __init__(self, origin, backend, directory):
        self.directory = directory
        self.state = {'accounts': {'buyer-a': {'account': {'id': 'test-actor'}}}}
        self.evidence = []
        self.client = self
    def close(self): pass
    def call(self, service, method, route, actor=None):
        self.evidence.append({'service':service,'method':method,'route':route,'status':200,'request_id':'test-real-request'})
    def run_phase(self, phase):
        with open(self.directory / 'phases.txt', 'a') as stream: stream.write(phase + '\\n')
        self.call('identity', 'GET', '/v1/contacts', 'buyer-a')
`);
  await new Promise((done,reject)=>{
    const child=spawn('python3',['-c',preparationProgram,runDir,'http://localhost:3000',runDir,revision],{stdio:'ignore'});
    child.once('error',reject);child.once('exit',code=>code===0?done():reject(new Error('Test preparation failed')));
  });
  assert.equal(await readFile(join(runDir,'phases.txt'),'utf8'),'accounts\nbootstrap\nonboard\ncontacts\n');
  const rows=JSON.parse(await readFile(join(runDir,'contacts-bound-evidence.json'),'utf8'));
  assert.equal(rows[0].actor_id,'test-actor');assert.equal(rows[0].provider_revision,revision);assert.equal(rows[0].request_id,'test-real-request');
  await prepare({origin:'http://localhost:3000',runDir,revision},(command,args)=>{
    assert.equal(command,'python3');assert.equal(args[0],'-c');assert.equal(args[1],preparationProgram);assert.equal(args.at(-1),revision);
    const child=new EventEmitter();queueMicrotask(()=>child.emit('exit',0));return child;
  });
}));

async function privatePage({discard=false,persist=false,operationChange=false,missingOperation=false}={}) {
  const {runInNewContext}=await import('node:vm');
  const password={type:'password',value:'',isConnected:true};
  const file={type:'file',value:'',files:[],isConnected:true,dispatchEvent(){}};
  const root={lang:'en',textContent:'عربي '.repeat(40)};
  const storage={};
  const operation={textContent:'00000000-0000-4000-8000-000000000001'};
  const world={window:{fetch:async()=>{}},localStorage:storage,sessionStorage:{},location:{search:'?test=retained'},crypto:globalThis.crypto,Event:class {},
    File:class {constructor(parts){this.parts=parts;}async text(){return this.parts.join('');}},
    DataTransfer:class {constructor(){this.files=[];this.items={add:item=>this.files.push(item)};}},
    document:{cookie:'',querySelectorAll:selector=>selector==='bdi'?(missingOperation?[]:[operation]):[password,file],querySelector:selector=>selector==='.bt-shell'?root:selector.includes('identity_evidence')?file:null}};
  const page={goto:async()=>{},waitFor:async()=>{},fill:async(selector,value)=>{password.value=value;},exists:async()=>true,
    evaluate:(fn,...args)=>runInNewContext(`(${fn.toString()})(...args)`,{...world,args}),
    click:async()=>{root.lang=root.lang==='en'?'ar':'en';if(operationChange)operation.textContent='00000000-0000-4000-8000-000000000002';if(discard)password.value='';if(persist)storage.private=password.value;}};
  return {page,world,password,file};
}
test('private forms are populated anew and retained only in mounted memory',async()=>{
  const {page,world,password,file}=await privatePage();
  await populatePrivateForm(page,'password');await populatePrivateForm(page,'file');
  assert.match(password.value,/^synthetic-private-/);assert.equal(file.files.length,1);
  const checks=await localeChecks(page,cell);
  assert.equal(checks.passwordMemoryOnly,true);assert.equal(checks.privateFilesMemoryOnly,true);assert.equal(checks.sameMountedInputs,true);
  assert.deepEqual(world.localStorage,{});assert.equal(world.window.__btN09,undefined);
});
test('private checks refuse lost state and persisted private values',async()=>{
  for(const options of [{discard:true},{persist:true}]) {
    const {page}=await privatePage(options);
    await populatePrivateForm(page,'password');await populatePrivateForm(page,'file');
    const checks=await localeChecks(page,cell);
    assert.equal(checks.passwordMemoryOnly,false);assert.equal(checks.privateFilesMemoryOnly,false);
  }
});

test('language switching preserves rendered operation references without a custom attribute',async()=>{
  const {page}=await privatePage();
  assert.equal((await localeChecks(page,cell)).sameOperation,true);
  for(const options of [{operationChange:true},{missingOperation:true}]) {
    const {page}=await privatePage(options);
    assert.equal((await localeChecks(page,cell)).sameOperation,false);
  }
});


test('prepared browser session survives handoff without another sign in or navigation',async()=>temporary(async directory=>{
  const {serveSession,connectSession}=await import('../features/ctx.mjs');
  const {duplexPair}=await import('node:stream');
  const {EventEmitter}=await import('node:events');
  let accept;
  const listen=handler=>{accept=handler;const server=new EventEmitter();server.listen=(path,done)=>done();server.close=()=>{};return server;};
  const connect=()=>{const [client,host]=duplexPair();queueMicrotask(()=>{accept(host);client.emit('connect');});return client;};
  const socket=join(directory,'page.sock');let closed=0;const calls=[];
  const page={goto:async path=>calls.push(path),url:async()=>'/en/test-page',evaluate:async(fn,...args)=>fn(...args)};
  const server=await serveSession({config:{},socket,directory},async()=>({page,close:async()=>{closed++;},screenshot:async path=>calls.push(path)}),{listen,secure:async()=>{}});
  try {
    const runner=await connectSession(socket,{connect});await runner.page.goto('/en/test-page');
    await runner.detach();await runner.close();assert.equal(closed,0);
    const controller=new AbortController();
    const observer=await connectSession(socket,{signal:controller.signal,connect});
    assert.equal(await observer.page.url(),'/en/test-page');
    assert.equal(await observer.page.evaluate(value=>value+1,2),3);
    controller.abort();await observer.close();
    assert.deepEqual(calls,['/en/test-page']);
  }finally{await server.close();}
  assert.equal(closed,1);
}));

test('private preparation replaces a static landing page with a live form and request reference',async()=>{
  const {prepareObservation}=await import('../../../../scripts/native-browser-adapter.mjs');
  const {page}=await privatePage();const roles=[],paths=[],submissions=[];
  const localeClick=page.click;
  page.click=async selector=>{if(selector==='.bt-locale-control')return localeClick();submissions.push(selector);};
  page.text=async()=> '00000000-0000-4000-8000-000000000001';
  page.url=async()=>'/en/help';
  page.goto=async path=>paths.push(path);
  const checks=await prepareObservation({page,cell,signIn:async role=>roles.push(role)});
  assert.deepEqual(roles,['buyer','buyer']);
  assert.deepEqual(paths,['/business/contacts','/seller/verification','/business/contacts?observation=contact']);
  assert.deepEqual(submissions,['form:has(input[name="reauth"]) button[type="submit"]']);
  for(const name of ['sameOperation','sameMountedInputs','sameQuery','noLanguageWrites','passwordMemoryOnly','privateFilesMemoryOnly'])assert.equal(checks[name],true,name);
});

test('runner saves bound preparation before handing over the live session',async()=>temporary(async runDir=>{
  const events=[];const feature={...manifest.features[0],...Object.fromEntries(['journey','negative','recovery'].map(name=>[name,async()=>({actor_id:'test-actor',operation_id:'test-operation'})]))};
  const checks={passwordMemoryOnly:true,privateFilesMemoryOnly:true};
  await run({origin:'http://localhost:3000',runDir,features:'F1',cells:cell.key},{revision,loadFeatures:async()=>[feature],prepare:async()=>{},
    browser:async()=>({socket:join(runDir,'test.sock'),page:{goto:async()=>{},url:async()=>'/en/test-page'},detach:async()=>{
      const saved=JSON.parse(await readFile(join(runDir,'n09-evidence',cell.key,'observation.json'),'utf8'));
      assert.equal(saved.provider_revision,revision);assert.deepEqual(saved.checks,checks);events.push('detach');
    },close:async()=>events.push('close')}),
    prerequisites:async()=>({N01:record()}),prepareObservation:async()=>{events.push('prepare');return checks;},
  });
  assert.deepEqual(events,['prepare','detach','close']);
  const saved=JSON.parse(await readFile(join(runDir,'n09-evidence',cell.key,'page.json'),'utf8'));
  assert.equal(saved.origin,'http://localhost:3000');assert.equal(saved.cell,cell.key);assert.equal(saved.provider_revision,revision);
}));

test('dialog checks skip hidden and disabled triggers and restore the desktop page',async()=>{
  const {dialogChecks}=await import('../../../../scripts/native-browser-adapter.mjs');
  const {runInNewContext}=await import('node:vm');
  for(const phone of [false,true]) {
    let selected,opened=false,navigated=false,cleaned=false;
    const paths=[];
    const document={activeElement:null,querySelectorAll:()=>navigated?[hidden,disabled,visible]:phone?[hidden,disabled,visible]:[hidden,disabled],
      querySelector:()=>opened?{contains:el=>el===document.activeElement}:null};
    const trigger=(width,disabled=false)=>({getBoundingClientRect:()=>({width,height:44}),matches:()=>disabled,getAttribute:()=>null,closest:()=>null,
      setAttribute(){selected=this;},removeAttribute(){cleaned=true;},focus(){document.activeElement=this;}});
    const hidden=trigger(0),disabled=trigger(44,true),visible=trigger(44);
    const world={window:{},document,getComputedStyle:()=>({visibility:'visible',display:'block'})};
    const page={url:async()=>'/en/test-operation?reference=test-operation',goto:async path=>{paths.push(path);navigated=true;},waitFor:async()=>{},
      evaluate:(fn,...args)=>runInNewContext(`(${fn.toString()})(...args)`,{...world,args}),
      click:async selector=>{assert.equal(selector,'[data-n09-dialog-trigger]');assert.equal(selected,visible);opened=true;},
      press:async key=>{if(key==='Escape'){opened=false;visible.focus();}}};
    assert.deepEqual(await dialogChecks(page),{dialog:true,escape:true});
    assert.deepEqual(paths,phone?[]:['/business/contacts','/en/test-operation?reference=test-operation']);
    assert.equal(cleaned,true);assert.equal(world.window.__btN09Invoker,undefined);
  }
});


test('context dispatches published public and internal gateway paths with stable references',async()=>{
  const {context}=await import('../features/ctx.mjs');
  const calls=[];
  const page={evaluate:async(fn,args)=>{calls.push(args);return {status:200,json:{},operation_id:'test-report-operation'};}};
  const ctx=context({page,origin:'http://localhost:3000',cell,revision});
  for(const path of ['/v1/contacts','/internal/v1/financial-reports?period=test-period']) {
    const result=await ctx.api('orders','GET',path);
    assert.equal(result.operation_id,'test-report-operation');
    assert.equal(calls.at(-1).path,path);
  }
  for(const path of ['//example.test/v1/contacts','https://example.test/v1/contacts',
    '/internal/v1/../../identity/v1/accounts','/v1/%2e%2e/accounts',
    '/internal/v1/reports#test-fragment','/v1/reports\\test-path','/v1/reports\ntest-path']) {
    await assert.rejects(ctx.api('orders','GET',path),/Invalid service request/);
  }
  await assert.rejects(ctx.api('../identity','GET','/v1/accounts'),/Invalid service request/);
  assert.equal(calls.length,2);
});

test('first setup error survives every scenario and close failure allows the next cell',async()=>temporary(async runDir=>{
  const cells=plan(matrix).slice(0,2), opened=[];
  const feature={...manifest.features[0],journey:()=>assert.fail(),negative:()=>assert.fail(),recovery:()=>assert.fail()};
  const results=await run({origin:'http://localhost:3000',runDir,features:'F1',cells:cells.map(cell=>cell.key).join(',')},{
    revision,loadFeatures:async()=>[feature],prepare:async()=>{},
    browser:async({cell})=>{
      opened.push(cell.key);
      return {page:{goto:async()=>{throw Error('test-navigation-failed');}},close:async()=>{
        if(cell.key===cells[0].key)throw Error('test-close-failed');
      }};
    },prerequisites:async()=>({N01:{state:'failed'}}),
  });
  assert.deepEqual(opened,cells.map(cell=>cell.key));
  for(const result of results) {
    assert.equal(result.error,'test-navigation-failed');
    assert.equal(result.state,'failed');assert.equal(result.signed_in,false);
    assert.deepEqual(result.scenarios,{journey:'failed',negative:'failed',recovery:'failed'});
    const saved=JSON.parse(await readFile(join(runDir,'n09-evidence',result.cell,'F1.json'),'utf8'));
    assert.deepEqual(saved,result);
  }
  assert.equal(results[0].cleanup,'failed');assert.equal(results[1].cleanup,undefined);
}));
