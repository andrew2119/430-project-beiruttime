import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readdir, rm, stat, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import * as ctx from './ctx.mjs';
import {navigate, navigationMatches} from './ctx.mjs';

const cell={locale:'en',theme:'light',width:390,height:844,dpr:1,mobile:true,touch:true};
const quietServer=()=>({once(){},listen(_socket,done){done();},close(){}});
const exists=path=>stat(path).then(()=>true,()=>false);
// Stands in for Chrome: answers browser commands on the debugging pipe, and on SIGTERM leaves a helper
// process rewriting the profile's network state, the way Chrome's network service does, before it exits.
const fakeBrowser=`#!${process.execPath}
const {mkdirSync}=require('node:fs');
const {Socket}=require('node:net');
const {spawn}=require('node:child_process');
const {join}=require('node:path');
const profile=process.argv.find(arg=>arg.startsWith('--user-data-dir=')).slice('--user-data-dir='.length);
mkdirSync(join(profile,'Default'));
// Socket streams, because a pending file stream read on the pipe would stop this process from exiting.
const replies=new Socket({fd:4,readable:false,writable:true});let buffer='';
new Socket({fd:3,readable:true,writable:false}).on('data',chunk=>{
  buffer+=chunk;let end;
  while((end=buffer.indexOf('\\0'))>=0) {
    const {id,method}=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);
    replies.write(JSON.stringify({id,result:method==='Target.createTarget'?{targetId:'page'}:method==='Target.attachToTarget'?{sessionId:'page'}:{}})+'\\0');
  }
});
const writer=\`const {renameSync,writeFileSync,writeSync}=require('node:fs');const {join}=require('node:path');
const folder=process.argv[1],end=Date.now()+400;let n=0;writeSync(1,'writing\\\\n');
while(Date.now()<end){try{const temporary=join(folder,'.TransportSecurity.'+n++);writeFileSync(temporary,'{}');renameSync(temporary,join(folder,'TransportSecurity'));}catch(error){if(error.code==='ENOENT')break;throw error;}}\`;
process.on('SIGTERM',()=>{
  const helper=spawn(process.execPath,['-e',writer,join(profile,'Default')],{detached:true,stdio:['ignore','pipe','ignore']});
  helper.stdout.once('data',()=>process.exit(0));
});
`;
async function withTemporaryFolder(run) {
  const root=await mkdtemp(join(tmpdir(),'bt-ctx-test-')),previous=process.env.TMPDIR,temporary=join(root,'tmp');
  await mkdir(temporary);process.env.TMPDIR=temporary;
  try{await run({root,temporary});}
  finally{if(previous===undefined)delete process.env.TMPDIR;else process.env.TMPDIR=previous;await rm(root,{recursive:true,force:true,maxRetries:10,retryDelay:100});}
}

test('root navigation accepts the locale root after redirect',async()=>{
  for(const language of ['en','ar']) {
    const origin='http://localhost:3000';
    for(const path of ['/',`/${language}`,`/${language}/`]) {
      let requested;
      await navigate({evaluate:async()=>({href:`${origin}/${language}`,ready:'complete'})},path,
        {origin,cell:{language}},async(method,params)=>{requested=params.url;return {};});
      assert.equal(requested,`${origin}/${language}`);
    }
    assert.equal(navigationMatches(`${origin}/${language}/?test=1`,`${origin}/${language}?test=1`),true);
    for(const actual of [`http://localhost:3001/${language}`,`${origin}/${language}?test=2`,
      `${origin}/${language}#test`,`${origin}/${language}/help`,`${origin}/${language==='en'?'ar':'en'}`]) {
      assert.equal(navigationMatches(actual,`${origin}/${language}`),false);
    }
    assert.equal(navigationMatches(`${origin}/${language}/help/`,`${origin}/${language}/help`),false);
    await assert.rejects(navigate({},'http://example.test/',{origin,cell:{language}},()=>assert.fail()),/configured origin/);
  }
});

test('closing the browser waits out late profile writes',async()=>{
  await withTemporaryFolder(async({root,temporary})=>{
    const browserPath=join(root,'browser');await writeFile(browserPath,fakeBrowser,{mode:0o700});
    const directory=await mkdtemp(join(temporary,'bt-session-'));
    const handle=await ctx.serveSession({config:{browserPath,origin:'http://127.0.0.1:9',cell},socket:join(directory,'page.sock'),directory},
      undefined,{listen:quietServer,secure:async()=>{}});
    await handle.close();
    assert.deepEqual(await readdir(temporary),[]);
  });
});

test('session folder is removed even when the browser close fails',async()=>{
  await withTemporaryFolder(async({temporary})=>{
    const directory=await mkdtemp(join(temporary,'bt-session-'));
    const handle=await ctx.serveSession({config:{},socket:join(directory,'page.sock'),directory},
      async()=>({close:async()=>{throw new Error('Browser closed');}}),{listen:quietServer,secure:async()=>{}});
    const first=handle.close(),second=handle.close();
    await assert.rejects(first,/Browser closed/);await assert.rejects(second,/Browser closed/);
    assert.equal(await exists(directory),false);
  });
});

test('an unavailable prepared session says why',async()=>{
  await withTemporaryFolder(async({root,temporary})=>{
    await assert.rejects(ctx.browser({browserPath:root,origin:'http://127.0.0.1:9',cell}),
      {message:'Prepared session unavailable: Installed browser required'});
    assert.deepEqual(await readdir(temporary),[]);
  });
});

test('browser start failures report a known reason and the failed command, never a path',()=>{
  assert.equal(ctx.launchReason?.(Object.assign(new Error('Browser command timed out'),{method:'Target.createTarget'})),'Browser command timed out in Target.createTarget');
  assert.equal(ctx.launchReason?.(new Error('Installed browser required')),'Installed browser required');
  assert.equal(ctx.launchReason?.(Object.assign(new Error('EACCES: permission denied, access \'/opt/secret/chrome\''),{code:'EACCES'})),'EACCES');
  assert.equal(ctx.launchReason?.(Object.assign(new Error('/opt/secret/chrome failed'),{method:'/opt/secret'})),'unexpected error');
});
