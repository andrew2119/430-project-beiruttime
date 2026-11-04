// Mac screenshot fallback. Navigation, emulation and all interactions stay in
// chrome-devtools-axi; only Chrome's native screenshot bytes bypass the MCP's
// filesystem sandbox. Use a dedicated headless Chrome at 127.0.0.1:3360.
// Plain --window-size=390 on macOS actually creates a 500px CSS viewport and
// crops its PNG, so axi's real device-metrics emulation is essential here.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdir, writeFile } from 'node:fs/promises';
const exec=promisify(execFile);
const shots='/Users/andrew/.harness/homes/430-project/firstmate/data/bt-cp-business/shots';
const env={...process.env,CHROME_DEVTOOLS_AXI_SESSION:'bt-cp-business',CHROME_DEVTOOLS_AXI_BROWSER_URL:'http://127.0.0.1:3360'};
const routes=[['business','/business','input[name="legal_name"]'],['contacts','/business/contacts','input[name="recipient"]'],['membership','/business/membership','input[name="subject"]'],['history','/business/review-history','.business-timeline'],['verification','/operations/verification','.business-queue button'],['intake','/business-intake','.ops-form .ui-select'],['moderation','/operations/moderation?case=00000000-0000-4000-8000-000000000007','.ops-private'],['dashboard','/operations/dashboard','.ops-queue-grid .ui-card'],['queue','/operations/dashboard/queues/inspection','.ops-queue-grid .ui-card']];
const cli=(...args)=>exec('chrome-devtools-axi',args,{env,maxBuffer:4*1024*1024});
async function run(script){
 await new Promise((ok,fail)=>{const child=execFile('chrome-devtools-axi',['run'],{env,maxBuffer:4*1024*1024},(error,stdout,stderr)=>error?fail(Error(stdout+stderr)):ok(stdout));child.stdin.end(script);});
}
async function screenshot(url,filename){
 const pages=await (await fetch('http://127.0.0.1:3360/json/list')).json();
 const target=pages.find(page=>page.type==='page'&&page.url===url);
 if(!target)throw Error('No screenshot target '+url);
 const data=await new Promise((ok,fail)=>{
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  ws.addEventListener('open',()=>ws.send(JSON.stringify({id:1,method:'Page.captureScreenshot',params:{format:'png',captureBeyondViewport:false}})));
  ws.addEventListener('error',fail);
  ws.addEventListener('message',event=>{const result=JSON.parse(event.data);if(result.id!==1)return;ws.close();if(result.error)fail(Error(JSON.stringify(result.error)));else ok(result.result.data);});
 });
 await writeFile(filename,Buffer.from(data,'base64'));
}
await mkdir(shots,{recursive:true});
for(const [size,viewport] of [['desktop','1440x1000x1'],['phone','390x844x1,mobile,touch']]){
 await cli('emulate','--viewport',viewport);
 for(const locale of ['en','ar'])for(const theme of ['light','dark'])for(const [name,path,ready] of routes){
  const url=`http://127.0.0.1:3357/${locale}${path}`;
  let detail='';
  if(name==='membership')detail=`await page.fill('form:not(:has(input[name="subject"])) input[name="business"]','00000000-0000-4000-8000-000000000003');await page.click('form:not(:has(input[name="subject"])) button[type="submit"]');await page.wait('.business-content .ui-badge');`;
  if(name==='verification')detail=`await page.click('.business-queue button');await page.wait('input[name="application_revision"]');`;
  if(name==='intake')detail=`if(!await page.eval(()=>document.querySelector('label.ops-form select')?.value)){await page.click('label.ops-form .ui-select');await page.wait('[role="menuitemradio"]');await page.click('[role="menuitemradio"][data-state="unchecked"]');}await page.wait('.ops-records button');await page.click('.ops-records button');await page.wait('input[readonly]');`;
  await run(`await page.open('http://127.0.0.1:3357/en/business');await page.eval("document.cookie='bt-theme=${theme}; Path=/; SameSite=Lax'");await page.open(${JSON.stringify(url)});await page.wait(${JSON.stringify(ready)});${detail}await page.eval(async()=>{await document.fonts.ready;return true;});await page.wait(350);`);
  const filename=`${shots}/${name}-${locale}-${size}-${theme}.png`;
  await screenshot(url,filename);console.log(JSON.stringify({name,locale,size,theme,filename}));
 }
 for(const theme of ['light','dark']){
  const url=`http://127.0.0.1:${theme==='dark'?3353:3352}/bt-business-reference`;
  await run(`await page.open(${JSON.stringify(url)});await page.wait('.proto-set-card');await page.eval(async()=>{await document.fonts.ready;return true;});await page.wait(350);`);
  await screenshot(url,`${shots}/cp-reference-controls-${size}-${theme}.png`);
 }
}
