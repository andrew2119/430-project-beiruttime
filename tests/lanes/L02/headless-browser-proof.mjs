// Bounded installed-Chrome fallback when the CLI cannot select a fresh page.
// The same connected proof scripts run through real Chrome's DevTools protocol.
import {spawn} from 'node:child_process';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const root=resolve('tests/lanes/L02');
const evidence=resolve(root,'evidence');
await mkdir(evidence,{recursive:true});
globalThis.fixture=JSON.parse(await readFile(resolve(root,'.contract-runtime/browser.json'),'utf8'));
const port=9232;
const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',[
  '--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
  '--hide-scrollbars',`--remote-debugging-port=${port}`,
  `--user-data-dir=${resolve(root,'.contract-runtime/headless-profile')}`,'about:blank',
],{stdio:'ignore'});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let socket;
const pending=new Map();let sequence=0;
async function call(method,params={}) {
  const id=++sequence;
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout: '+method));},15000);
    pending.set(id,{resolve:result=>{clearTimeout(timer);resolve(result);},reject:error=>{clearTimeout(timer);reject(error);}});
    socket.send(JSON.stringify({id,method,params}));
  });
}
try {
  let target;
  for(let i=0;i<100;i++) {
    try {target=(await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(item=>item.type==='page');if(target)break;}catch{}
    await delay(100);
  }
  if(!target) throw new Error('Owned headless Chrome did not start');
  socket=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
  let documentStatus;
  socket.addEventListener('message',event=>{
    const message=JSON.parse(event.data);
    if(message.method==='Network.responseReceived'&&message.params.type==='Document')documentStatus=message.params.response.status;
    const waiter=pending.get(message.id);
    if(waiter){pending.delete(message.id);message.error?waiter.reject(new Error(JSON.stringify(message.error))):waiter.resolve(message.result);}
  });
  await call('Page.enable');await call('Runtime.enable');await call('Network.enable');
  globalThis.page={
    async eval(js) {
      let expression=typeof js==='function'?`(${js.toString()})()`:js;
      const result=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
      if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description??result.exceptionDetails.text);
      return result.result.value;
    },
    async open(url) {
      documentStatus=undefined;
      await call('Page.navigate',{url});
      for(let i=0;i<100;i++) {
        if(await page.eval(`location.href===${JSON.stringify(url)}&&document.readyState==='complete'`))return {url,status:documentStatus};
        await delay(50);
      }
      throw new Error('Navigation did not complete: '+url);
    },
    async wait(selector,timeout=15000) {
      if(typeof selector==='number')return delay(selector);
      const end=Date.now()+timeout;
      while(Date.now()<end){if(await page.eval(`!!document.querySelector(${JSON.stringify(selector)})`))return;await delay(50);}
      throw new Error('Missing selector '+selector+': '+await page.eval('document.querySelector("main")?.innerText'));
    },
    async fill(selector,value) {
      await page.eval(`(() => {const el=document.querySelector(${JSON.stringify(selector)});if(!el)throw new Error('Field missing');el.focus();el.value=${JSON.stringify(value)};el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return true;})()`);
    },
    async click(selector) {
      // A user cannot submit while a preceding file action owns the form bulkhead.
      for(let i=0;i<100;i++) {
        if(await page.eval(`!!document.querySelector(${JSON.stringify(selector)})&&!document.querySelector(${JSON.stringify(selector)}).disabled`))break;
        await delay(50);
      }
      await page.eval(`(() => {const el=document.querySelector(${JSON.stringify(selector)});if(!el)throw new Error('Action missing');el.scrollIntoView({block:'center'});el.click();return true;})()`);
    },
  };
  const oldLog=console.log;
  async function driver(file,output) {
    const lines=[];console.log=(...args)=>lines.push(args.map(String).join(' '));
    try {await import(pathToFileURL(resolve(root,file)).href+'?run='+Date.now());}
    finally {console.log=oldLog;await writeFile(resolve(evidence,output),lines.join('\n')+'\n');}
  }
  await call('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await page.open('http://localhost:3202/en/business');
  await driver('browser-public.mjs','public-desktop.json');
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:3,mobile:true});
  await call('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1});
  await driver('browser-public.mjs','public-phone.json');
  await call('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await call('Emulation.setTouchEmulationEnabled',{enabled:false});
  await driver('browser-private.mjs','private-interactions.json');
  await driver('browser-private-matrix.mjs','private-desktop.json');
  let screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  await writeFile(resolve(evidence,'private-desktop-ar-dark.png'),Buffer.from(screenshot.data,'base64'));
  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:3,mobile:true});
  await call('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1});
  await driver('browser-private-matrix.mjs','private-phone.json');
  screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  await writeFile(resolve(evidence,'private-phone-ar-dark.png'),Buffer.from(screenshot.data,'base64'));
  // A real dependency outage, not an intercepted response: stop only this test's
  // bounded Identity fixture and prove that neither an editable private form nor
  // a false success acknowledgement survives failed session restoration.
  await writeFile(resolve(root,'.contract-runtime/stop-browser'),'');
  let stopped=false;
  for(let i=0;i<100;i++) {
    try {await fetch('http://127.0.0.1:8202/health/ready',{signal:AbortSignal.timeout(300)});}
    catch {stopped=true;break;}
    await delay(50);
  }
  if(!stopped)throw new Error('Owned Identity fixture did not stop for outage proof');
  const outage=[];
  for(const locale of ['en','ar']) {
    await page.open(`http://localhost:3202/${locale}/business/contacts`);
    await page.wait('.business-workspace [role="alert"]');
    const result=await page.eval(() => ({
      locale:document.documentElement.lang,width:innerWidth,
      message:document.querySelector('.business-workspace [role="alert"]').innerText,
      editable:!!document.querySelector('.business-workspace input'),
      falseSuccess:!!document.querySelector('.business-feedback[role="status"]'),
      retry:!!document.querySelector('.business-workspace [role="alert"] button'),
    }));
    if(result.locale!==locale||result.width!==390||result.editable||result.falseSuccess||!result.retry)throw new Error('Outage recovery failed: '+JSON.stringify(result));
    outage.push(result);
  }
  await writeFile(resolve(evidence,'private-outage.json'),JSON.stringify(outage,null,2)+'\n');
  console.log('Four real private workflows, forty-eight connected public/private EN/AR light/dark desktop/390px cells and two real dependency-outage recovery cells passed through installed headless Chrome.');
} finally {
  socket?.close();chrome.kill('SIGTERM');
  await new Promise(resolve=>{if(chrome.exitCode!==null)return resolve();chrome.once('exit',resolve);});
}
