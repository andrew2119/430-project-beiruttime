// Headless screenshot fallback with explicit device metrics; a narrow PNG alone does not prove phone layout.
import { spawn } from 'node:child_process';
import { mkdir, writeFile, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
const base=process.argv[2]??'http://localhost:3105';
const output=resolve('tests/lanes/L05/artifacts/screens');
const profile=resolve('tests/lanes/L05/artifacts',`headless-${process.pid}`);
await mkdir(output,{recursive:true});
const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',[
  '--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run','--no-default-browser-check',
  '--remote-debugging-pipe',`--user-data-dir=${profile}`],{stdio:['ignore','ignore','ignore','pipe','pipe']});
let counter=0, buffer=''; const waiting=new Map();
chrome.stdio[4].on('data',chunk=>{
  buffer+=chunk.toString();
  let boundary;
  while((boundary=buffer.indexOf('\0'))>=0) {
    const frame=buffer.slice(0,boundary);buffer=buffer.slice(boundary+1);
    if(!frame)continue;
    const message=JSON.parse(frame);const job=waiting.get(message.id);
    if(job) {waiting.delete(message.id);clearTimeout(job.timeout);message.error?job.reject(new Error(message.error.message)):job.resolve(message.result);}
  }
});
function send(method,params={},sessionId) {
  const id=++counter;
  return new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>{waiting.delete(id);reject(new Error(`Headless timeout: ${method}`));},15000);
    waiting.set(id,{resolve,reject,timeout});
    chrome.stdio[3].write(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})})+'\0');
  });
}
const results=[];
try {
  const {targetId}=await send('Target.createTarget',{url:'about:blank'});
  const {sessionId}=await send('Target.attachToTarget',{targetId,flatten:true});
  await send('Page.enable',{},sessionId);
  for(const phone of [false,true]) for(const locale of ['en','ar']) for(const theme of ['light','dark']) {
    const width=phone?390:1280,height=phone?844:900;
    await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:phone?3:1,mobile:phone},sessionId);
    await send('Emulation.setTouchEmulationEnabled',{enabled:phone},sessionId);
    await send('Network.setCookie',{name:'bt-theme',value:theme,url:base,path:'/'},sessionId);
    await send('Page.navigate',{url:`${base}/${locale}/seller/auctions`},sessionId);
    let state;
    for(let retry=0;retry<60;retry++) {
      await new Promise(resolve=>setTimeout(resolve,100));
      const response=await send('Runtime.evaluate',{expression:'({ready:document.readyState,lang:document.documentElement.lang,title:document.querySelector("h1")?.textContent,session:document.querySelector(".auction-feature")?.dataset.sessionState})',returnByValue:true},sessionId);
      state=response.result?.value;
      if(state?.ready==='complete'&&state.lang===locale&&state.title&&state.session&&state.session!=='restoring')break;
      if(retry===59)throw new Error(`Session boundary did not settle: ${JSON.stringify(state)}`);
    }
    await send('Runtime.evaluate',{expression:'document.fonts.ready.then(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))',awaitPromise:true,returnByValue:true},sessionId);
    const response=await send('Runtime.evaluate',{expression:'({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,lang:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth,title:document.querySelector("h1")?.textContent,session:document.querySelector(".auction-feature")?.dataset.sessionState,controls:[...document.querySelectorAll(".auction-feature .button,.preferences button")].map(e=>({left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,height:e.getBoundingClientRect().height}))})',returnByValue:true},sessionId);
    const metrics=response.result?.value;
    if(metrics?.width!==width||metrics.lang!==locale||metrics.theme!==theme||metrics.overflow||metrics.dir!==(locale==='ar'?'rtl':'ltr')||metrics.controls.some(control=>control.left<0||control.right>width||control.height<44))throw new Error(`Invalid headless matrix state: ${JSON.stringify(metrics)}`);
    const name=`${locale}-${phone?'phone':'desktop'}-${theme}`;
    const screenshot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false,fromSurface:true},sessionId);
    await writeFile(resolve(output,`${name}.png`),Buffer.from(screenshot.data,'base64'));
    results.push({name,...metrics});
  }
  await writeFile(resolve(output,'matrix.json'),JSON.stringify(results,null,2)+'\n');
  console.log(JSON.stringify(results,null,2));
} finally {
  await send('Browser.close').catch(()=>{});
  chrome.kill();
  for(const job of waiting.values()){clearTimeout(job.timeout);job.reject(new Error('Headless browser closed'));}
  await new Promise(resolve=>{if(chrome.exitCode!==null)resolve();else chrome.once('exit',resolve);});
  await rm(profile,{recursive:true,force:true});
}
