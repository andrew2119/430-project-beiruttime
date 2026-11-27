import {spawn, fork} from 'node:child_process';
import {createServer, createConnection} from 'node:net';
import {chmod} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {mkdtemp, rm, writeFile, access, stat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve, isAbsolute} from 'node:path';
import {randomUUID} from 'node:crypto';
import {constants} from 'node:fs';

const pause = ms => new Promise(done => setTimeout(done, ms));
export function navigationMatches(actual, expected) {
  const current = new URL(actual), target = new URL(expected);
  const canonical = path => /^\/(en|ar)\/$/.test(path) ? path.slice(0,-1) : path;
  return current.origin === target.origin && current.search === target.search
    && current.hash === target.hash && canonical(current.pathname) === canonical(target.pathname);
}
export async function navigate(page, path, {origin, cell}, call) {
  const url = new URL(path,origin);
  if (url.origin !== origin) throw new Error('Page must use configured origin');
  if (!/^\/(en|ar)(\/|$)/.test(url.pathname)) url.pathname = `/${cell.locale ?? cell.language}${url.pathname}`;
  if (/^\/(en|ar)\/$/.test(url.pathname)) url.pathname = url.pathname.slice(0,-1);
  const result = await call('Page.navigate',{url:url.href});
  if (result.errorText) throw new Error('Navigation failed');
  const end = Date.now()+12000;
  while (Date.now()<end) {
    const state = await page.evaluate(()=>({href:location.href,ready:document.readyState}));
    if (state.ready === 'complete' && navigationMatches(state.href,url.href)) return;
    await pause(50);
  }
  throw new Error('Navigation timed out');
}

export async function localBrowser({browserPath, origin, cell, signal, profileRoot, loopbackOnly = false}) {
  if (!browserPath || !isAbsolute(browserPath) || signal?.aborted) throw new Error('Installed browser required');
  await access(browserPath,constants.X_OK);
  if(!(await stat(browserPath)).isFile())throw new Error('Installed browser required');
  const profile = await mkdtemp(join(profileRoot ?? tmpdir(), 'bt-browser-'));
  const network = loopbackOnly ? ['--disable-background-networking', '--disable-component-update',
    '--disable-quic', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
    '--proxy-server=http://127.0.0.1:1'] : [];
  const child = spawn(browserPath, ['--headless=new', '--no-first-run', '--no-default-browser-check',
    ...network, '--remote-debugging-pipe', `--user-data-dir=${profile}`, 'about:blank'],
  {stdio:['ignore','ignore','ignore','pipe','pipe']});
  const pending = new Map(); let sequence = 0, buffer = '', sessionId, closed = false, closing;
  const rejectPending = () => { for (const item of pending.values()) item.reject(new Error('Browser closed')); pending.clear(); };
  const exited = new Promise(done => {child.once('exit', done); child.once('error', done);});
  child.once('error', rejectPending); child.once('exit', rejectPending);
  child.stdio[4].setEncoding('utf8');
  child.stdio[4].on('data', chunk => {
    buffer += chunk; let end;
    while ((end = buffer.indexOf('\0')) >= 0) {
      const message = JSON.parse(buffer.slice(0,end)); buffer = buffer.slice(end+1);
      const item = pending.get(message.id);
      if (item) {pending.delete(message.id); message.error ? item.reject(new Error('Browser command failed')) : item.resolve(message.result);}
    }
  });
  async function call(method, params = {}, target = sessionId) {
    if (closed || signal?.aborted) throw new Error('Browser closed');
    const id = ++sequence;
    return new Promise((resolveCall,reject) => {
      const timer = setTimeout(() => {pending.delete(id); reject(new Error('Browser command timed out'));}, 12000);
      pending.set(id, {resolve:value=>{clearTimeout(timer);resolveCall(value);}, reject:error=>{clearTimeout(timer);reject(error);}});
      child.stdio[3].write(JSON.stringify({id,method,params,...(target ? {sessionId:target} : {})})+'\0');
    });
  }
  function close() {
    if (closing) return closing;
    closed = true; rejectPending();
    closing=(async()=>{
      child.kill('SIGTERM');
      const timer = setTimeout(()=>child.kill('SIGKILL'),1000);
      await exited; clearTimeout(timer);
      // An ephemeral runner may retain its private profile until machine teardown.
      if (profileRoot === undefined) await rm(profile,{recursive:true,force:true});
      signal?.removeEventListener('abort', abort);
    })();
    return closing;
  }
  const abort = () => {void close();}; signal?.addEventListener('abort',abort,{once:true});
  try {
    const {targetId} = await call('Target.createTarget',{url:'about:blank'},null);
    ({sessionId} = await call('Target.attachToTarget',{targetId,flatten:true},null));
    await call('Page.enable'); await call('Runtime.enable'); await call('Network.enable');
    await call('Network.setExtraHTTPHeaders',{headers:{'Accept-Language':cell.locale ?? cell.language}});
    await call('Network.setCookie',{name:'bt-theme',value:cell.theme,url:origin,path:'/',sameSite:'Lax'});
    await call('Browser.setDownloadBehavior',{behavior:'deny'},null);
    await call('Emulation.setDeviceMetricsOverride',{width:cell.width,height:cell.height,deviceScaleFactor:cell.dpr,mobile:cell.mobile});
    await call('Emulation.setTouchEmulationEnabled',{enabled:cell.touch});
    await call('Emulation.setLocaleOverride',{locale:cell.locale ?? cell.language});
    await call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:cell.theme},{name:'prefers-reduced-motion',value:'reduce'}]});
    const page = {
      async evaluate(fn,...args) {
        const result = await call('Runtime.evaluate',{expression:`(${fn.toString()})(...${JSON.stringify(args)})`,awaitPromise:true,returnByValue:true});
        if (result.exceptionDetails) throw new Error('Page evaluation failed');
        return result.result.value;
      },
      goto:path=>navigate(page,path,{origin,cell},call),
      async click(selector) {const point=await page.evaluate(selector=>{const el=document.querySelector(selector);if(!el)throw Error();el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};},selector);await call('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});await call('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});},
      async fill(selector,value) {await page.evaluate((selector,value)=>{const el=document.querySelector(selector);if(!el)throw Error();el.focus();const setter=Object.getOwnPropertyDescriptor(el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;setter.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));},selector,value);},
      async select(selector,value) {await page.evaluate((selector,value)=>{const el=document.querySelector(selector);if(!el)throw Error();el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));},selector,value);},
      async press(key) {const keys={Tab:9,Enter:13,Escape:27};if(!keys[key])throw new Error('Unsupported key');await call('Input.dispatchKeyEvent',{type:'keyDown',key,code:key,windowsVirtualKeyCode:keys[key]});await call('Input.dispatchKeyEvent',{type:'keyUp',key,code:key,windowsVirtualKeyCode:keys[key]});},
      text:selector=>page.evaluate(selector=>document.querySelector(selector)?.textContent ?? null,selector),
      exists:selector=>page.evaluate(selector=>!!document.querySelector(selector),selector),
      async waitFor(selector,{timeout=12000}={}) {const end=Date.now()+timeout;while(Date.now()<end){if(await page.exists(selector))return;await pause(50);}throw new Error('Element timed out');},
      url:()=>page.evaluate(()=>location.href),
      async reload() {await page.goto(await page.url());},
    };
    return {page,call,close,async screenshot(path){const result=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(path,Buffer.from(result.data,'base64'));}};
  } catch(error) {await close().catch(()=>{});throw error;}
}

export const preparationProgram = `
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from connected_walkthrough import Walkthrough
origin, directory, revision = sys.argv[2:5]
walk = Walkthrough(origin, 'native', Path(directory))
original = walk.call
def bound_call(service, method, route, actor=None, *args, **kwargs):
    start = len(walk.evidence)
    try:
        return original(service, method, route, actor, *args, **kwargs)
    finally:
        identity = walk.state.get('accounts', {}).get(actor, {}).get('account', {}).get('id')
        for row in walk.evidence[start:]:
            if identity and row.get('service') == service and row.get('method') == method and row.get('route') == route.split('?')[0]:
                row.setdefault('actor_id', identity)
                row.setdefault('provider_revision', revision)
walk.call = bound_call
try:
    for phase in ['accounts', 'bootstrap', 'onboard', 'contacts']:
        walk.evidence = []
        walk.run_phase(phase)
        path = Path(directory) / (phase + '-bound-evidence.json')
        with open(path, 'w', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            json.dump(walk.evidence, stream)
finally:
    walk.client.close()
`;
export async function prepare({origin,runDir,revision}, launch=spawn) {
  await new Promise((done,reject)=>{
    const child=launch('python3',['-c',preparationProgram,resolve('tests/integration/sprint-1'),origin,runDir,revision],{stdio:'ignore'});
    const timer=setTimeout(()=>child.kill('SIGTERM'),180000);
    child.once('error',()=>{clearTimeout(timer);reject(new Error('Account preparation unavailable'));});
    child.once('exit',code=>{clearTimeout(timer);code===0?done():reject(new Error('Account preparation failed'));});
  });
}
export function context({page,origin,cell,revision}) {
  const accounts=new Map(); let active;
  const names={'buyer':'buyer-a','buyer2':'buyer-b','private-seller':'seller','dealer':'dealer','brand':'brand','operator':'operator','reviewer':'operator'};
  const uniq=prefix=>`${prefix}-${randomUUID()}`;
  async function request(service,method,path,body,token) {
    if(!/^[a-z][a-z0-9-]*$/.test(service) || typeof path!=='string' || !/^\/(?:internal\/)?v[0-9]+\//.test(path)
      || /[\\#\s]/.test(path))throw new Error('Invalid service request');
    const gatewayPath=`/api/web/v1/${service}${path}`;
    const destination=new URL(gatewayPath,origin);
    if(destination.origin!==origin || destination.pathname+destination.search!==gatewayPath)throw new Error('Invalid service request');
    return page.evaluate(async ({service,method,path,body,token,key})=>{
      const response=await fetch(`/api/web/v1/${service}${path}`,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','Idempotency-Key':key,...(token?{Authorization:`Bearer ${token}`}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});
      return {status:response.status,json:await response.json(),operation_id:response.headers.get('x-request-id')};
    },{service,method,path,body,token,key:uniq('n09')});
  }
  async function signIn(role) {
    if(!names[role])throw new Error('Unsupported role');
    const result=await request('identity','POST','/v1/accounts/login',{email:`${names[role]}.s1@example.test`,password:['Course','demo','passphrase!'].join('-')});
    if(result.status!==200 || !result.json.account?.id || !result.json.access_token)throw new Error('Sign in failed');
    const account={actor_id:result.json.account.id,name:result.json.account.display_name,token:result.json.access_token};
    accounts.set(role,account);active=role;
    await page.reload();
    return {actor_id:account.actor_id,name:account.name};
  }
  return {page,origin,cell,revision,uniq,signIn,
    signedInRole:()=>active,
    isActor:id=>[...accounts.values()].some(account=>account.actor_id===id),
    actor:role=>accounts.has(role)&&active===role?Promise.resolve({actor_id:accounts.get(role).actor_id,name:accounts.get(role).name}):signIn(role),
    async api(service,method,path,body,options={}) {const role=options.as ?? active;if(role&&!accounts.has(role))await signIn(role);return request(service,method,path,body,accounts.get(role)?.token);},
  };
}

export async function connectSession(socket, {signal,connect=createConnection}={}) {
  if(typeof socket!=='string' || !isAbsolute(socket))throw new Error('Prepared session unavailable');
  const connection=connect(socket);
  await new Promise((done,reject)=>{connection.once('connect',done);connection.once('error',reject);});
  const pending=new Map();let next=0,buffer='',detached=false;
  const fail=()=>{for(const item of pending.values())item.reject(new Error('Prepared session closed'));pending.clear();};
  connection.on('error',fail);connection.on('close',fail);
  connection.on('data',chunk=>{
    buffer+=chunk;
    let end;
    while((end=buffer.indexOf('\n'))>=0) {
      const message=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);
      const item=pending.get(message.id);if(!item)continue;pending.delete(message.id);
      message.error?item.reject(new Error(typeof message.error==='string' && ['Navigation failed','Navigation timed out','Page must use configured origin','Browser closed','Browser command timed out','Session cleanup failed'].includes(message.error) ? message.error : 'Prepared page command failed')):item.resolve(message.value);
    }
  });
  function call(method,args=[],closing=false) {
    if(!closing)signal?.throwIfAborted();
    if(connection.destroyed)return Promise.reject(new Error('Prepared session closed'));
    return new Promise((resolve,reject)=>{const id=++next;pending.set(id,{resolve,reject});connection.write(JSON.stringify({id,method,args})+'\n');});
  }
  const page=Object.fromEntries(['goto','click','fill','select','press','text','exists','waitFor','url','reload'].map(method=>[method,(...args)=>call(method,args)]));
  page.evaluate=(fn,...args)=>call('evaluate',[fn.toString(),...args]);
  return {page,socket,screenshot:path=>call('screenshot',[path]),
    async detach(){await call('detach');detached=true;connection.end();},
    async close(){if(detached || connection.destroyed)return;try{await call('close',[],true);}finally{connection.destroy();}},
  };
}
export async function browser(config) {
  const directory=await mkdtemp(join(tmpdir(),'bt-session-'));
  const socket=join(directory,'page.sock');
  const child=fork(fileURLToPath(import.meta.url),['--session'],{stdio:['ignore','ignore','ignore','ipc'],detached:true});
  try {
    await new Promise((done,reject)=>{
      const timer=setTimeout(()=>reject(new Error('Prepared session timed out')),15000);
      child.once('message',message=>{clearTimeout(timer);message.ready?done():reject(new Error('Prepared session unavailable'));});
      child.once('error',error=>{clearTimeout(timer);reject(error);});
      child.once('exit',()=>{clearTimeout(timer);reject(new Error('Prepared session closed'));});
      child.send({config:{browserPath:config.browserPath,origin:config.origin,cell:config.cell},socket,directory});
    });
    child.disconnect();child.unref();
    return await connectSession(socket,{signal:config.signal});
  }catch(error){child.kill();await rm(directory,{recursive:true,force:true});throw error;}
}
export async function serveSession({config,socket,directory}, launch=localBrowser,{listen=createServer,secure=chmod}={}) {
  let session,server,timer,stopping=false;
  const stop=async()=>{
    if(stopping)return;stopping=true;clearTimeout(timer);
    server?.close();await session?.close();await rm(directory,{recursive:true,force:true});
  };
  process.once('SIGTERM',()=>{void stop();});
  try {
    session=await launch(config);
    server=listen(connection=>{
      let buffer='',detached=false,queue=Promise.resolve();
      connection.on('error',()=>{});
      connection.on('close',()=>{if(!detached)void stop();});
      connection.on('data',chunk=>{
        buffer+=chunk;let end;
        while((end=buffer.indexOf('\n'))>=0) {
          const line=buffer.slice(0,end);buffer=buffer.slice(end+1);
          queue=queue.then(async()=>{
            let message;
            try {
              message=JSON.parse(line);const {method,args}=message;let value;
              if(method==='detach')detached=true;
              else if(method==='close'){await stop();connection.end(JSON.stringify({id:message.id})+'\n');return;}
              else if(method==='screenshot')value=await session.screenshot(...args);
              else if(method==='evaluate')value=await session.page.evaluate(Function('return ('+args[0]+')')(),...args.slice(1));
              else if(['goto','click','fill','select','press','text','exists','waitFor','url','reload'].includes(method))value=await session.page[method](...args);
              else throw new Error('Unknown page command');
              connection.write(JSON.stringify({id:message.id,value})+'\n');
            }catch(error){connection.write(JSON.stringify({id:message?.id,error:['Navigation failed','Navigation timed out','Page must use configured origin','Browser closed','Browser command timed out'].includes(error.message) ? error.message : message?.method==='close' ? 'Session cleanup failed' : true})+'\n');}
          });
        }
      });
    });
    await new Promise((done,reject)=>{server.once('error',reject);server.listen(socket,done);});
    await secure(socket,0o600);
    timer=setTimeout(()=>{void stop();},30*60*1000);
    process.send?.({ready:true});
    return {close:stop};
  }catch(error){process.send?.({ready:false});await stop();if(!process.send)throw error;}
}
if(process.argv[2]==='--session' && process.send)process.once('message',message=>{void serveSession(message);});
