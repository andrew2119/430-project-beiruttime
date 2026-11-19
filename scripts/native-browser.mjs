import {readFile, writeFile, mkdir, stat, access, unlink} from 'node:fs/promises';
import {constants} from 'node:fs';
import {resolve, relative, isAbsolute} from 'node:path';
import {inflateSync} from 'node:zlib';
import {pathToFileURL} from 'node:url';

export const cases = ['keyboard', 'focus', 'dialog', 'escape', 'reducedMotion',
  'longArabic', 'overflow', 'safeAreas', 'touchFloor', 'inputFloor',
  'sameMountedInputs', 'passwordMemoryOnly', 'privateFilesMemoryOnly',
  'sameQuery', 'sameOperation', 'noLanguageWrites', 'oppositeSidebar'];
const fail = message => { throw new Error(message); };
export function plan(matrix) {
  const expected = [
    {id:'desktop',width:1440,height:900,dpr:1,mobile:false,touch:false},
    {id:'phone',width:390,height:844,dpr:3,mobile:true,touch:true},
  ];
  if(matrix.schema_version !== 1 || JSON.stringify(matrix.devices) !== JSON.stringify(expected)
    || JSON.stringify(matrix.languages) !== '["en","ar"]'
    || JSON.stringify(matrix.themes) !== '["light","dark"]'
    || JSON.stringify(matrix.required_proofs) !== '["N01","N05"]') fail('Invalid matrix contract');
  return matrix.devices.flatMap(device => matrix.languages.flatMap(language =>
    matrix.themes.map(theme => ({...device,language,theme,key:`${device.id}-${language}-${theme}`}))));
}
const reference = value => typeof value === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(value);
export function featureManifest(value) {
  if(value?.schema_version !== 1 || !reference(value.revision)
    || !Array.isArray(value.features) || value.features.length !== 64
    || new Set(value.features.map(item=>item?.feature_id)).size !== 64
    || value.features.some(item=>!reference(item?.feature_id) || !reference(item.proof_id)
      || !reference(item.proof_revision))) return null;
  return {schema_version:1,revision:value.revision,features:value.features.map(item=>({
    feature_id:item.feature_id,proof_id:item.proof_id,proof_revision:item.proof_revision}))};
}
export function featureCoverage(result, manifest, cell) {
  if(!manifest) return null;
  return manifest.features.map(mapping=>{
    const record = result.feature_proofs?.[mapping.feature_id];
    if(record?.schema_version !== 1 || record.error || record.boundary !== 'connected'
      || record.state !== 'passed' || record.signed_in !== true
      || record.manifest_revision !== manifest.revision || record.cell !== cell.key
      || record.feature_id !== mapping.feature_id || record.proof_id !== mapping.proof_id
      || record.proof_revision !== mapping.proof_revision
      || !['operation_id','actor_id','provider_revision'].every(key=>reference(record[key]))
      || !['journey','negative','recovery'].every(key=>record.scenarios?.[key] === 'passed')) {
      fail('Missing connected feature coverage');
    }
    return {...mapping,schema_version:1,boundary:'connected',state:'passed',signed_in:true,
      manifest_revision:manifest.revision,cell:cell.key,operation_id:record.operation_id,
      actor_id:record.actor_id,provider_revision:record.provider_revision,
      scenarios:{journey:'passed',negative:'passed',recovery:'passed'}};
  });
}
export function validate(result, cell) {
  if(result?.error || result?.status !== 'passed') fail('Browser result failed');
  const m = result.metrics;
  for(const key of ['width','height','dpr','mobile','touch','language','theme']) {
    if(m?.[key] !== cell[key]) fail(`Measured ${key} differs`);
  }
  if(m.direction !== (cell.language === 'ar' ? 'rtl' : 'ltr')) fail('Direction differs');
  for(const name of cases) if(result.checks?.[name] !== true) fail(`Missing observation: ${name}`);
}
export function crc32(bytes) {
  let crc = 0xffffffff;
  for(const byte of bytes) {
    crc ^= byte;
    for(let bit=0;bit<8;bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
export async function validateScreenshot(path, cell, io = {readFile}) {
  const bytes = await io.readFile(path);
  if(bytes.length < 45 || bytes.length > 64*1024*1024
    || bytes.subarray(0,8).toString('hex') !== '89504e470d0a1a0a') fail('Invalid screenshot');
  let offset=8, header=false, ended=false;
  const data=[];
  while(offset < bytes.length) {
    if(offset+12 > bytes.length) fail('Invalid screenshot chunk');
    const size=bytes.readUInt32BE(offset), end=offset+12+size;
    if(end>bytes.length) fail('Invalid screenshot chunk');
    const type=bytes.toString('ascii',offset+4,offset+8);
    if(crc32(bytes.subarray(offset+4,end-4)) !== bytes.readUInt32BE(end-4)) fail('Invalid screenshot checksum');
    if(!header) {
      if(type !== 'IHDR' || size !== 13) fail('Invalid screenshot header');
      const h=bytes.subarray(offset+8,end-4);
      if(h.readUInt32BE(0)!==cell.width*cell.dpr || h.readUInt32BE(4)!==cell.height*cell.dpr
        || h[8]!==8 || ![2,6].includes(h[9]) || h[10] || h[11] || h[12]) fail('Invalid screenshot geometry');
      header=h[9];
    } else if(type==='IHDR') fail('Duplicate screenshot header');
    if(type==='IDAT') data.push(bytes.subarray(offset+8,end-4));
    if(type==='IEND') { if(size || end!==bytes.length) fail('Invalid screenshot end'); ended=true; }
    offset=end;
  }
  if(!ended || !data.length) fail('Empty screenshot');
  const stride=cell.width*cell.dpr*(header===6?4:3)+1;
  const length=stride*cell.height*cell.dpr;
  const pixels=inflateSync(Buffer.concat(data),{maxOutputLength:length});
  if(pixels.length!==length) fail('Invalid screenshot pixels');
  for(let row=0;row<cell.height*cell.dpr;row++) if(pixels[row*stride]>4) fail('Invalid screenshot filter');
}
async function bounded(action, milliseconds, controller) {
  let timer;
  try { return await Promise.race([Promise.resolve().then(action),new Promise((_,reject)=>{
    timer=setTimeout(()=>{controller?.abort();reject(new Error('Observation deadline exceeded'));},milliseconds);
  })]); } finally { clearTimeout(timer); }
}
export async function run(matrix, options, adapter, io = {readFile,writeFile,mkdir,unlink}) {
  const cells = plan(matrix);
  const manifest = featureManifest(matrix.feature_manifest);
  const report = {schema_version:1, boundary:'connected', cells:[], fixture_results:[],
    deferred:['database','restore','load'], feature_manifest:manifest,
    required:manifest ? [] : ['feature-manifest']};
  await io.mkdir(options.runDir,{recursive:true});
  for(const cell of cells) {
    if(report.cells.length === cells.length) break;
    let session, opening;
    const controller=new AbortController();
    try {
      opening=Promise.resolve().then(()=>adapter.open({signal:controller.signal,browserPath:options.browserPath, origin:options.origin,
        cell, sandbox:true, download:false, reducedMotion:'reduce'}));
      session = await bounded(()=>opening,options.timeoutMs ?? 15000,controller);
      const result = await bounded(()=>session.observe({schema_version:1, cases, requiredProofs:matrix.required_proofs,featureManifest:manifest,signal:controller.signal}),options.timeoutMs ?? 15000,controller);
      validate(result,cell);
      for(const proof of matrix.required_proofs) {
        const record = result.proofs?.[proof];
        if(record?.schema_version !== 1 || record.error || record.boundary !== 'connected' || record.state !== 'passed'
          || !['operation_id','actor_id','provider_revision'].every(key=>
            /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(String(record[key] ?? '')))
          || record.signed_in !== true) fail(`Missing connected proof: ${proof}`);
      }
      const featureProofs = featureCoverage(result,manifest,cell);
      const screenshot = resolve(options.runDir,`${cell.key}.png`);
      await bounded(async()=>{
        try { await io.unlink(screenshot); }
        catch(error) { if(error.code !== 'ENOENT') throw error; }
      },options.timeoutMs ?? 15000,controller);
      await bounded(()=>session.screenshot(screenshot,{signal:controller.signal}),options.timeoutMs ?? 15000,controller);
      await bounded(()=>validateScreenshot(screenshot,cell,io),options.timeoutMs ?? 15000,controller);
      report.cells.push({key:cell.key,state:'passed',checks:[...cases],feature_proofs:featureProofs,
        proofs:Object.fromEntries(matrix.required_proofs.map(name=>[name,Object.fromEntries(
          ['schema_version','boundary','state','signed_in','operation_id','actor_id','provider_revision'].map(key=>[key,result.proofs[name][key]]))])),metrics:Object.fromEntries(['width','height','dpr','mobile','touch','language','theme','direction'].map(key=>[key,result.metrics[key]]))});
    } catch {
      report.cells.push({key:cell.key,state:'incomplete',reason:'observation-incomplete'});
    } finally {
      controller.abort();
      if(opening) {
        const cleanup = session ? Promise.resolve().then(()=>session.close())
          : opening.then(late=>late.close(),()=>{});
        try { await bounded(()=>cleanup,options.timeoutMs ?? 15000); }
        catch {
          report.required.push(`${cell.key}: session cleanup`);
          Object.assign(report.cells.at(-1),{state:'incomplete',reason:'cleanup-unconfirmed'});
        }
      }
    }
  }
  const device = matrix.physical_device_record;
  if(!device) report.required.push('physical-device');
  else {
    try {
      const record = JSON.parse(await bounded(()=>io.readFile(resolve(device),'utf8'),options.timeoutMs ?? 15000));
      if(record.schema_version !== 1 || record.boundary !== 'physical-device'
        || record.state !== 'passed' || !record.device || !record.observed_at
        || !record.observer || cells.filter(c=>c.mobile).some(c=>!record.cells?.includes(c.key))) {
        fail('Incomplete physical-device record');
      }
    } catch { report.required.push('physical-device'); }
  }
  report.complete = report.cells.every(c=>c.state === 'passed') && !report.required.length;
  await io.writeFile(resolve(options.runDir,'native-browser.json'),JSON.stringify(report,null,2)+'\n');
  return report;
}
export function parse(args) {
  const options = {};
  for(let i=0;i<args.length;i++) {
    const key = args[i];
    if(['--plan','--require-all'].includes(key)) options[key.slice(2)] = true;
    else if(['--origin','--run-dir','--matrix'].includes(key) && args[i+1] && !args[i+1].startsWith('--')) options[key.slice(2)] = args[++i];
    else fail('Invalid argument');
  }
  return options;
}
async function main() {
  const options = parse(process.argv.slice(2));
  const matrix = JSON.parse(await readFile(options.matrix ?? 'scripts/native-browser-matrix.json','utf8'));
  const cells = plan(matrix);
  if(options.plan) { console.log(JSON.stringify({schema_version:1,cells,cases,requiredProofs:matrix.required_proofs,featureManifest:featureManifest(matrix.feature_manifest),requiredFeatures:64,physicalDevice:'required',execution:false},null,2)); return; }
  if(!options.origin || !options['run-dir']) fail('Origin and run directory required');
  const origin = new URL(options.origin);
  if(!['http:','https:'].includes(origin.protocol) || origin.username || origin.password
    || origin.pathname !== '/' || origin.search || origin.hash) fail('Invalid origin');
  const browserPath = process.env.BT_NATIVE_BROWSER;
  if(process.platform !== 'linux' || !browserPath || !isAbsolute(browserPath)) fail('Installed Linux browser required');
  await access(browserPath,constants.X_OK);
  if(!(await stat(browserPath)).isFile()) fail('Browser must be an executable file');
  if(!matrix.adapter) fail('N01/N05 adapter unavailable; connected and physical-device proof deferred');
  if(isAbsolute(matrix.adapter) || relative(process.cwd(),resolve(matrix.adapter)).startsWith('..')) fail('Adapter must belong to the repository');
  const adapter = await import(pathToFileURL(resolve(matrix.adapter)).href);
  const report = await run(matrix,{origin:origin.origin,runDir:resolve(options['run-dir']),browserPath},adapter);
  if(!report.complete) process.exitCode = 1;
}
if(process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error=>{console.error(error.message);process.exitCode=1;});
}
