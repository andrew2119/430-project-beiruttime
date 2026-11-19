import {deflateSync} from 'node:zlib';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {crc32,plan,validate,validateScreenshot,run,cases,parse,featureManifest,featureCoverage} from '../../../scripts/native-browser.mjs';
const matrix = {...JSON.parse(await readFile(new URL('../../../scripts/native-browser-matrix.json',import.meta.url))),feature_manifest:null};
const cells = plan(matrix);
function result(cell) {
  return {status:'passed',metrics:{...cell,direction:cell.language === 'ar'?'rtl':'ltr'},
    checks:Object.fromEntries(cases.map(name=>[name,true])),
    proofs:Object.fromEntries(matrix.required_proofs.map(name=>[name,{schema_version:1,boundary:'connected',
      state:'passed',signed_in:true,actor_id:'synthetic-person',operation_id:'synthetic-operation',provider_revision:1}]))};
}
function png(cell) {
  const chunk=(type,data)=>{
    const bytes=Buffer.alloc(data.length+12);bytes.writeUInt32BE(data.length);
    bytes.write(type,4);data.copy(bytes,8);
    bytes.writeUInt32BE(crc32(bytes.subarray(4,-4)),bytes.length-4);return bytes;
  };
  const header=Buffer.alloc(13);header.writeUInt32BE(cell.width*cell.dpr);
  header.writeUInt32BE(cell.height*cell.dpr,4);header[8]=8;header[9]=2;
  return Buffer.concat([Buffer.from('89504e470d0a1a0a','hex'),chunk('IHDR',header),
    chunk('IDAT',deflateSync(Buffer.alloc((cell.width*cell.dpr*3+1)*cell.height*cell.dpr))),chunk('IEND',Buffer.alloc(0))]);
}
function stub(change = ()=>{}) {
  const files = new Map(), calls=[];
  const io = {mkdir:async()=>{},writeFile:async(path,data)=>files.set(path,data),
    unlink:async path=>{calls.push({removed:path});if(!files.delete(path))throw Object.assign(Error('Missing file'),{code:'ENOENT'});},
    readFile:async path=>{if(!files.has(path))throw Error('Missing file');return files.get(path);}};
  const adapter = {open:async config=>{
    calls.push(config); const cell=config.cell;
    return {observe:async request=>{assert.deepEqual(request.cases,cases);const value=result(cell);change(value);return value;},
      screenshot:async path=>files.set(path,png(cell)),close:async()=>calls.push('closed')};
  }};
  return {io,adapter,calls,files};
}
test('eight exact cells and all observations',()=>{
  assert.equal(cells.length,8);assert.equal(new Set(cells.map(c=>c.key)).size,8);
  for(const cell of cells) validate(result(cell),cell);
  for(const key of ['width','height','dpr','mobile','touch','language','theme','direction']) {
    const value=result(cells[4]);value.metrics[key]=null;assert.throws(()=>validate(value,cells[4]));
  }
  for(const name of cases) {const value=result(cells[0]);delete value.checks[name];assert.throws(()=>validate(value,cells[0]));}
  const value=result(cells[0]);value.error='failure';assert.throws(()=>validate(value,cells[0]));
  assert.throws(()=>plan({...matrix,languages:['en']}));
});
test('screenshot file must exist, contain bytes and match pixel dimensions',async()=>{
  for(const cell of cells) await validateScreenshot('image',cell,{readFile:async()=>png(cell)});
  for(const bytes of [Buffer.alloc(0),Buffer.from('invalid'),png(cells[0])]) {
    await assert.rejects(validateScreenshot('image',cells[4],{readFile:async()=>bytes}));
  }
  await assert.rejects(validateScreenshot('image',cells[0],{readFile:async()=>{throw Error('missing');}}));
});
test('bounded execution keeps physical proof incomplete and closes every session',async()=>{
  const s=stub();const report=await run(matrix,{runDir:'output',origin:'http://localhost:3000',browserPath:'installed'},s.adapter,s.io);
  assert.equal(report.cells.filter(c=>c.state==='passed').length,8);
  assert.equal(report.complete,false);assert.deepEqual(report.required,['feature-manifest','physical-device']);
  assert.equal(s.calls.filter(c=>c==='closed').length,8);
  for(const config of s.calls.filter(c=>c.cell)) {
    assert.equal(config.sandbox,true);assert.equal(config.download,false);assert.equal(config.reducedMotion,'reduce');
  }
});
test('a previous screenshot cannot satisfy a capture that writes nothing',async()=>{
  const s=stub();
  for(const cell of cells) s.files.set(resolve('output',`${cell.key}.png`),png(cell));
  s.adapter.open=async config=>({
    observe:async()=>result(config.cell),
    screenshot:async path=>assert.equal(s.files.has(path),false),
    close:async()=>s.calls.push('closed'),
  });
  const report=await run(matrix,{runDir:'output'},s.adapter,s.io);
  assert.equal(report.complete,false);
  assert.ok(report.cells.every(cell=>cell.state==='incomplete'));
  assert.equal(s.calls.filter(call=>call.removed).length,8);
  assert.equal(s.calls.filter(call=>call==='closed').length,8);
});
test('failed screenshot removal prevents capture and remains incomplete',async()=>{
  const s=stub();let captured=0;
  s.io.unlink=async()=>{throw Object.assign(Error('Removal denied'),{code:'EACCES'});};
  s.adapter.open=async config=>({observe:async()=>result(config.cell),
    screenshot:async()=>{captured++;},close:async()=>{}});
  const report=await run(matrix,{runDir:'output'},s.adapter,s.io);
  assert.equal(captured,0);
  assert.ok(report.cells.every(cell=>cell.state==='incomplete'));
  assert.equal(report.complete,false);
});
test('zero-exit error payload, clamped width and fixture proofs cannot pass',async()=>{
  for(const change of [r=>r.error='failure',r=>r.metrics.width=500,r=>r.proofs.N01.boundary='fixture',r=>delete r.proofs.N05]) {
    const s=stub(change);const report=await run(matrix,{runDir:'output'},s.adapter,s.io);
    assert.equal(report.complete,false);assert.ok(report.cells.every(c=>c.state==='incomplete'));
    assert.equal(s.calls.filter(c=>c==='closed').length,8);
  }
});
test('error-bearing prerequisite records cannot pass or expose private errors',async()=>{
  for(const proof of matrix.required_proofs) {
    const s=stub(value=>{value.proofs[proof].error='private prerequisite detail';});
    const report=await run(matrix,{runDir:'output'},s.adapter,s.io);
    assert.equal(report.complete,false);
    assert.equal(report.cells.length,8);
    assert.ok(report.cells.every(cell=>cell.state==='incomplete' && !cell.proofs));
    assert.equal(s.calls.filter(call=>call==='closed').length,8);
    assert.equal(s.calls.filter(call=>call.removed).length,0);
    assert.ok(!JSON.stringify(report).includes('private prerequisite detail'));
  }
});
test('missing adapter session and cleanup failures remain required',async()=>{
  const s=stub();s.adapter.open=async()=>{throw Error('unavailable');};
  const report=await run(matrix,{runDir:'output'},s.adapter,s.io);
  assert.ok(report.cells.every(c=>c.state==='incomplete'));
});
test('strict argument parsing',()=>{
  assert.deepEqual(parse(['--plan','--require-all']),{plan:true,'require-all':true});
  assert.throws(()=>parse(['--origin']));assert.throws(()=>parse(['--unknown']));
});

test('unsettled observations and failed cleanup remain incomplete',async()=>{
  for(const hanging of [true,false]) {
    const s=stub();s.adapter.open=async config=>({
      observe:async()=>hanging ? new Promise(()=>{}) : result(config.cell),
      screenshot:async path=>s.files.set(path,png(config.cell)),
      close:async()=>{throw Error('private detail');},
    });
    const report=await run(matrix,{runDir:'output',timeoutMs:5},s.adapter,s.io);
    assert.equal(report.complete,false);assert.equal(report.required.length,10);
    assert.ok(!JSON.stringify(report).includes('private detail'));
  }
});

test('external device record can complete only the matching phone cells',async()=>{
  const s=stub();s.files.set('device.json',JSON.stringify({schema_version:1,boundary:'physical-device',
    state:'passed',device:'physical handset',observed_at:'2026-11-16',observer:'reviewer',
    cells:cells.filter(c=>c.mobile).map(c=>c.key)}));
  const original=s.io.readFile;s.io.readFile=async path=>path.endsWith('device.json')?s.files.get('device.json'):original(path);
  const report=await run({...matrix,physical_device_record:'device.json'},{runDir:'output'},s.adapter,s.io);
  assert.equal(report.complete,false);assert.ok(report.required.includes('feature-manifest'));assert.equal(report.cells[0].proofs.N01.operation_id,'synthetic-operation');
  s.files.set('device.json','{}');
  assert.equal((await run({...matrix,physical_device_record:'device.json'},{runDir:'output'},s.adapter,s.io)).complete,false);
});

test('startup deadline signals cancellation and closes late sessions',async()=>{
  const s=stub();let closed=0,aborted=0;
  s.adapter.open=async({signal})=>{
    await new Promise(resolve=>signal.addEventListener('abort',()=>{aborted++;resolve();},{once:true}));
    return {close:async()=>{closed++;}};
  };
  const report=await run(matrix,{runDir:'output',timeoutMs:5},s.adapter,s.io);
  assert.equal(report.complete,false);assert.equal(aborted,8);assert.equal(closed,8);
});


test('late startup cleanup is awaited before another cell opens',async()=>{
  for(const mode of ['success','failure','deadline','unsettled']) {
    const s=stub();let opened=0, closed=0, active=false;
    s.adapter.open=async({signal})=>{
      if(mode==='success')assert.equal(active,false);active=true;opened++;
      if(mode==='unsettled') return new Promise(()=>{});
      await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));
      return {close:async()=>{
        closed++;
        if(mode==='failure') throw Error('private cleanup detail');
        if(mode==='deadline') return new Promise(()=>{});
        await new Promise(resolve=>setTimeout(resolve,1));active=false;
      }};
    };
    const report=await run(matrix,{runDir:'output',timeoutMs:5},s.adapter,s.io);
    assert.equal(report.complete,false);
    assert.equal(opened,8);
    assert.equal(closed,mode==='unsettled'?0:8);
    assert.equal(report.required.includes(`${cells[0].key}: session cleanup`),mode!=='success');
    assert.equal(report.cells.length,8);
    assert.ok(!JSON.stringify(report).includes('private cleanup detail'));
  }
});

test('hanging screenshot reads still close sessions and finish the report',async()=>{
  const s=stub();s.io.readFile=async()=>new Promise(()=>{});
  const report=await run(matrix,{runDir:'output',timeoutMs:5},s.adapter,s.io);
  assert.equal(report.complete,false);
  assert.ok(report.cells.every(cell=>cell.state==='incomplete'));
  assert.equal(s.calls.filter(call=>call==='closed').length,8);
  assert.ok(s.files.has(resolve('output','native-browser.json')));
});

test('hanging physical record read remains required and finishes the report',async()=>{
  const s=stub(), read=s.io.readFile;
  s.io.readFile=async path=>path.endsWith('device.json')?new Promise(()=>{}):read(path);
  const report=await run({...matrix,physical_device_record:'device.json'},
    {runDir:'output',timeoutMs:5},s.adapter,s.io);
  assert.equal(report.complete,false);
  assert.deepEqual(report.required,['feature-manifest','physical-device']);
  assert.equal(s.calls.filter(call=>call==='closed').length,8);
  assert.ok(s.files.has(resolve('output','native-browser.json')));
});

const manifest = {schema_version:1,revision:'coverage-1',features:Array.from({length:64},(_,index)=>({
  feature_id:`synthetic-feature-${index+1}`,proof_id:`synthetic-proof-${index+1}`,proof_revision:'1'}))};
function covered(value, cell) {
  value.feature_proofs=Object.fromEntries(manifest.features.map(mapping=>[mapping.feature_id,{
    ...mapping,schema_version:1,manifest_revision:manifest.revision,cell:cell.key,
    boundary:'connected',state:'passed',signed_in:true,operation_id:'stable-operation',
    actor_id:'synthetic-person',provider_revision:'1',scenarios:{journey:'passed',negative:'passed',recovery:'passed'},
  }]));
  return value;
}
test('versioned feature mapping requires 64 distinct complete entries',()=>{
  assert.deepEqual(featureManifest(manifest),manifest);
  for(const value of [null,{}, {...manifest,schema_version:2},{...manifest,revision:''},
    {...manifest,features:manifest.features.slice(1)},
    {...manifest,features:Array(64).fill(manifest.features[0])},
    {...manifest,features:manifest.features.map(item=>({...item,proof_revision:''}))}]) {
    assert.equal(featureManifest(value),null);
  }
});
test('each cell requires exact connected feature bindings and all scenario outcomes',()=>{
  for(const cell of cells) {
    assert.equal(featureCoverage(covered(result(cell),cell),manifest,cell).length,64);
    for(const change of [r=>delete r.feature_proofs,r=>delete r.feature_proofs[manifest.features[0].feature_id],
      ...['schema_version','manifest_revision','cell','feature_id','proof_id','proof_revision',
        'boundary','state','signed_in','operation_id','actor_id','provider_revision'].map(key=>r=>{
          r.feature_proofs[manifest.features[0].feature_id][key]=null;
        }), ...['journey','negative','recovery'].map(key=>r=>{
          r.feature_proofs[manifest.features[0].feature_id].scenarios[key]='pending';
        })]) {
      const value=covered(result(cell),cell);change(value);
      assert.throws(()=>featureCoverage(value,manifest,cell));
    }
  }
});
test('device and prerequisites never replace connected feature evidence',async()=>{
  const s=stub();s.files.set(resolve('device.json'),JSON.stringify({schema_version:1,
    boundary:'physical-device',state:'passed',device:'physical handset',observed_at:'2026-11-16',
    observer:'reviewer',cells:cells.filter(c=>c.mobile).map(c=>c.key)}));
  const configured={...matrix,feature_manifest:manifest,physical_device_record:'device.json'};
  let report=await run(configured,{runDir:'output'},s.adapter,s.io);
  assert.equal(report.complete,false);assert.ok(report.cells.every(c=>c.state==='incomplete'));
  s.adapter.open=async({cell})=>({observe:async request=>{
    assert.deepEqual(request.featureManifest,manifest);return covered(result(cell),cell);
  },screenshot:async path=>s.files.set(path,png(cell)),close:async()=>{}});
  report=await run(configured,{runDir:'output'},s.adapter,s.io);
  assert.equal(report.complete,true);
  assert.ok(report.cells.every(c=>c.feature_proofs.length===64));
  assert.equal(report.cells[0].feature_proofs[0].operation_id,'stable-operation');
});
