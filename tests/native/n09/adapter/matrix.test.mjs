import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {deflateSync} from 'node:zlib';
import {resolve} from 'node:path';
import {run, cases, crc32, featureManifest, plan} from '../../../../scripts/native-browser.mjs';

const matrix=JSON.parse(await readFile(new URL('../../../../scripts/native-browser-matrix.json',import.meta.url)));
function screenshot(cell) {
  const chunk=(type,data)=>{
    const bytes=Buffer.alloc(data.length+12);
    bytes.writeUInt32BE(data.length);bytes.write(type,4);data.copy(bytes,8);
    bytes.writeUInt32BE(crc32(bytes.subarray(4,-4)),bytes.length-4);
    return bytes;
  };
  const header=Buffer.alloc(13);
  header.writeUInt32BE(cell.width*cell.dpr);header.writeUInt32BE(cell.height*cell.dpr,4);
  header[8]=8;header[9]=2;
  return Buffer.concat([Buffer.from('89504e470d0a1a0a','hex'),chunk('IHDR',header),
    chunk('IDAT',deflateSync(Buffer.alloc((cell.width*cell.dpr*3+1)*cell.height*cell.dpr))),chunk('IEND',Buffer.alloc(0))]);
}
function fixture({includeFeatures=true,physical=false,capture=true,cleanup=true}={}) {
  const files=new Map();let closed=0;
  const io={mkdir:async()=>{},writeFile:async(path,data)=>files.set(path,data),
    unlink:async path=>{files.delete(path);},readFile:async path=>files.get(path)};
  const adapter={open:async({cell})=>({
    observe:async request=>{
      const proof={schema_version:1,boundary:'connected',state:'passed',signed_in:true,
        operation_id:'synthetic-operation',actor_id:'synthetic-person',provider_revision:'1'};
      if(physical)files.set(resolve('test-device.json'),JSON.stringify({schema_version:1,
        boundary:'physical-device',state:'passed',device:'physical handset',observed_at:'2026-11-16',
        observer:'reviewer',cells:['phone-en-light','phone-en-dark','phone-ar-light','phone-ar-dark']}));
      return {status:'passed',metrics:{...cell,direction:cell.language==='ar'?'rtl':'ltr'},
        checks:Object.fromEntries(cases.map(name=>[name,true])),proofs:{N01:proof,N05:proof},
        feature_proofs:includeFeatures&&request.featureManifest?Object.fromEntries(request.featureManifest.features.map(mapping=>[
          mapping.feature_id,{...proof,...mapping,manifest_revision:request.featureManifest.revision,cell:cell.key,
            scenarios:{journey:'passed',negative:'passed',recovery:'passed'}}])):undefined};
    },screenshot:async path=>{if(capture)files.set(path,screenshot(cell));},close:async()=>{closed++;if(!cleanup)throw Error('test-cleanup-failed');},
  })};
  return {io,adapter,files,closed:()=>closed};
}
test('configured manifest requires feature evidence and keeps physical proof required',async()=>{
  assert.equal(featureManifest(matrix.feature_manifest).features.length,64);
  for(const includeFeatures of [true,false]) {
    const stub=fixture({includeFeatures});
    const report=await run(matrix,{runDir:'test-output'},stub.adapter,stub.io);
    assert.equal(report.complete,false);
    assert.deepEqual(report.required,['physical-device']);
    assert.ok(report.cells.every(cell=>cell.state===(includeFeatures?'passed':'incomplete')));
    assert.equal(stub.closed(),8);
    if(includeFeatures)for(const cell of report.cells) {
      assert.equal(cell.proofs.N01.operation_id,'synthetic-operation');
      assert.equal(cell.feature_proofs.length,64);
      assert.ok(cell.feature_proofs.every(proof=>proof.operation_id==='synthetic-operation'));
    }
  }
});
test('explicit absent manifest preserves the original incomplete coverage contract',async()=>{
  for(const includeFeatures of [true,false]) {
    const stub=fixture({includeFeatures});
    const report=await run({...matrix,feature_manifest:null},{runDir:'test-output'},stub.adapter,stub.io);
    assert.deepEqual(report.required,['feature-manifest','physical-device']);
    assert.ok(report.cells.every(cell=>cell.state==='passed'));
    assert.equal(report.complete,false);assert.equal(stub.closed(),8);
    for(const cell of report.cells)assert.equal(cell.proofs.N01.operation_id,'synthetic-operation');
  }
});
test('physical proof completes configured coverage only with feature evidence',async()=>{
  for(const includeFeatures of [true,false]) {
    const stub=fixture({includeFeatures,physical:true});
    const report=await run({...matrix,physical_device_record:'test-device.json'},
      {runDir:'test-output'},stub.adapter,stub.io);
    assert.equal(report.complete,includeFeatures);
    assert.deepEqual(report.required,[]);assert.equal(stub.closed(),8);
  }
});
test('configured feature evidence cannot replace a screenshot or confirmed cleanup',async()=>{
  for(const options of [{capture:false},{cleanup:false}]) {
    const stub=fixture(options);
    const report=await run(matrix,{runDir:'test-output'},stub.adapter,stub.io);
    assert.equal(report.complete,false);
    assert.ok(report.cells.slice(options.cleanup===false?1:0).every(cell=>cell.state==='incomplete'));
    if(options.cleanup===false)assert.ok(report.required.includes(`${report.cells[0].key}: session cleanup`));
    assert.ok(report.required.includes('physical-device'));
    assert.equal(report.required.includes('feature-manifest'),false);
    assert.equal(stub.closed(),8);
  }
});
test('physical proof leaves an explicitly absent manifest required',async()=>{
  const stub=fixture({physical:true});
  const report=await run({...matrix,feature_manifest:null,physical_device_record:'test-device.json'},
    {runDir:'test-output'},stub.adapter,stub.io);
  assert.equal(report.complete,false);
  assert.deepEqual(report.required,['feature-manifest']);
  assert.ok(report.cells.every(cell=>cell.state==='passed'));
  assert.equal(stub.closed(),8);
});

test('previous captures cannot satisfy a missing capture with either manifest fixture',async()=>{
  for(const configured of [matrix,{...matrix,feature_manifest:null}]) {
    const stub=fixture({capture:false});let removed=0;
    for(const cell of plan(configured))stub.files.set(resolve('test-output',`${cell.key}.png`),screenshot(cell));
    const unlink=stub.io.unlink;
    stub.io.unlink=async path=>{assert.ok(stub.files.has(path));removed++;await unlink(path);};
    const report=await run(configured,{runDir:'test-output'},stub.adapter,stub.io);
    assert.equal(report.complete,false);
    assert.ok(report.cells.every(cell=>cell.state==='incomplete'));
    assert.equal(removed,8);assert.equal(stub.closed(),8);
  }
});

test('refused screenshot removal prevents capture with either manifest fixture',async()=>{
  for(const configured of [matrix,{...matrix,feature_manifest:null}]) {
    const stub=fixture();let captures=0;
    const open=stub.adapter.open;
    stub.io.unlink=async()=>{throw Object.assign(Error('test-removal-refused'),{code:'EACCES'});};
    stub.adapter.open=async config=>{
      const session=await open(config);
      session.screenshot=async()=>{captures++;};
      return session;
    };
    const report=await run(configured,{runDir:'test-output'},stub.adapter,stub.io);
    assert.equal(captures,0);
    assert.equal(stub.closed(),8);
    assert.equal(report.complete,false);
    assert.ok(report.cells.every(cell=>cell.state==='incomplete'));
    assert.deepEqual(report.required,configured.feature_manifest?['physical-device']:['feature-manifest','physical-device']);
  }
});

test('unsettled observations and refused cleanup keep explicit absent coverage required',async()=>{
  for(const hanging of [true,false]) {
    const stub=fixture({cleanup:false});const open=stub.adapter.open;
    stub.adapter.open=async config=>{
      const session=await open(config);
      if(hanging)session.observe=async()=>new Promise(()=>{});
      return session;
    };
    const report=await run({...matrix,feature_manifest:null},{runDir:'test-output',timeoutMs:5},stub.adapter,stub.io);
    assert.equal(report.complete,false);
    assert.deepEqual(report.required,['feature-manifest',...plan(matrix).map(cell=>`${cell.key}: session cleanup`),'physical-device']);
    assert.equal(stub.closed(),8);
    assert.ok(!JSON.stringify(report).includes('test-cleanup-failed'));
  }
});

test('unsettled physical record reads preserve explicit absent coverage and finish',async()=>{
  const stub=fixture();const read=stub.io.readFile;
  stub.io.readFile=async path=>path.endsWith('test-device.json')?new Promise(()=>{}):read(path);
  const report=await run({...matrix,feature_manifest:null,physical_device_record:'test-device.json'},
    {runDir:'test-output',timeoutMs:5},stub.adapter,stub.io);
  assert.equal(report.complete,false);
  assert.deepEqual(report.required,['feature-manifest','physical-device']);
  assert.ok(report.cells.every(cell=>cell.state==='passed'));
  assert.equal(stub.closed(),8);
  assert.ok(stub.files.has(resolve('test-output','native-browser.json')));
});

test('one refused close marks its cell incomplete and later cells still pass',async()=>{
  const stub=fixture();const open=stub.adapter.open;let opened=0;
  stub.adapter.open=async config=>{
    opened++;
    const session=await open(config);
    if(opened===1)session.close=async()=>{throw Error('test-close-failed');};
    return session;
  };
  const report=await run(matrix,{runDir:'test-output'},stub.adapter,stub.io);
  assert.equal(opened,8);
  assert.equal(report.complete,false);
  assert.equal(report.cells[0].state,'incomplete');
  assert.equal(report.cells[0].reason,'cleanup-unconfirmed');
  assert.ok(report.required.includes(`${report.cells[0].key}: session cleanup`));
  assert.ok(report.cells.slice(1).every(cell=>cell.state==='passed'));
});
