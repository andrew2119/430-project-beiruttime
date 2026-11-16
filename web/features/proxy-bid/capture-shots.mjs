// Screenshot-only headless Chrome driver. AXI owns all interaction/DOM proofs.
// On macOS --window-size=390 crops a >=500px viewport, and --screenshot may
// capture before hydration. CDP sets an actual 390px viewport and waits for data.
import { spawn } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const shots=process.env.BT_BUYER_SHOTS;
if(!shots)throw new Error('Set BT_BUYER_SHOTS to the task screenshot directory');
const profile=await mkdtemp(join(dirname(fileURLToPath(import.meta.url)),'.proof-chrome-'));
const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',['--headless=new','--disable-gpu','--hide-scrollbars','--window-size=1440,1000','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
let ws;
try {
  const endpoint=await new Promise((resolve,reject)=>{let log='';const timer=setTimeout(()=>reject(new Error('Chrome startup timeout')),15000);chrome.stderr.on('data',chunk=>{log+=chunk;const match=/DevTools listening on (ws:\/\/[^\s]+)/.exec(log);if(match){clearTimeout(timer);resolve(match[1]);}});chrome.on('exit',code=>reject(new Error(`Chrome exited ${code}`)));});
  const port=new URL(endpoint).port;
  const targets=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
  let id=0;const pending=new Map();
  ws.addEventListener('message',event=>{const message=JSON.parse(event.data);if(!message.id)return;const callbacks=pending.get(message.id);pending.delete(message.id);if(message.error)callbacks.reject(new Error(message.error.message));else callbacks.resolve(message.result);});
  const call=(method,params={})=>new Promise((resolve,reject)=>{const key=++id;pending.set(key,{resolve,reject});ws.send(JSON.stringify({id:key,method,params}));});
  const evaluate=async expression=>(await call('Runtime.evaluate',{expression,returnByValue:true})).result.value;
  const waitFor=async expression=>{for(let n=0;n<200;n++){if(await evaluate(expression))return;await new Promise(resolve=>setTimeout(resolve,100));}throw new Error(`Capture readiness timed out: ${expression}`);};
  await call('Page.enable');await call('Network.enable');
  const routes={buyer:['buyer','.buyer-activity-row'],bidding:['buyer/auctions/00000000-0000-4000-8000-000000000003','.proxy-panel input'],checkout:['checkout?watch=00000000-0000-4000-8000-000000000006&quote=00000000-0000-4000-8000-000000000004','input[name="watch_id"]'],order:['checkout/00000000-0000-4000-8000-000000000005','.checkout-result'],prices:['prices?quote_id=00000000-0000-4000-8000-000000000004','input[name="subject"]'],buying:['buying?reservation_id=00000000-0000-4000-8000-000000000005&quote_id=00000000-0000-4000-8000-000000000004','input[name="draft_subject"]'],inbox:['inbox','.l07-inbox-row']};
  for(const reference of process.env.BT_CAPTURE_GALLERY==='1'?[false,true]:[false])for(const theme of ['light','dark'])for(const [device,width,height] of [['desktop',1440,1000],['phone',390,844]]) {
    await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width===390});
    await call('Network.setCookie',{name:'bt-theme',value:theme,url:'http://127.0.0.1',path:'/'});
    const cases=reference?[['reference','en','buyer-reference','.ph-card-title']]:['en','ar'].flatMap(locale=>Object.entries(routes).map(([name,[path,selector]])=>[name,locale,`${locale}/${path}`,selector]));
    for(const [name,locale,path,selector] of cases) {
      await call('Page.navigate',{url:`http://127.0.0.1:${reference?33515:33517}/${path}`});
      await waitFor(`document.readyState==='complete' && !!document.querySelector(${JSON.stringify(selector)}) && document.documentElement.dataset.theme===${JSON.stringify(theme)}`);
      await new Promise(resolve=>setTimeout(resolve,500));
      const widthSeen=await evaluate('innerWidth');if(widthSeen!==width)throw new Error(`Not a real ${width}px viewport: ${widthSeen}`);
      const {data}=await call('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false});
      await writeFile(join(shots,`${name}-${locale}-${theme}-${device}.png`),Buffer.from(data,'base64'));
      console.log(`captured ${name} ${locale} ${theme} ${device} (${widthSeen}px)`);
    }
  }
} finally {
  ws?.close();chrome.kill('SIGTERM');
  await new Promise(resolve=>{if(chrome.exitCode!==null)return resolve();chrome.once('exit',resolve);setTimeout(resolve,3000);});
  await rm(profile,{recursive:true,force:true});
}
