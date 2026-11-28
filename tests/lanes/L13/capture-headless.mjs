// Capture only: interaction stays in the task's chrome-devtools-axi session.
import {writeFile} from 'node:fs/promises';
const [origin,output]=process.argv.slice(2);
const targets=await (await fetch('http://127.0.0.1:58139/json/list')).json();
const target=targets.find(t=>t.type==='page'&&t.url.startsWith(origin));
if(!target)throw Error('Own headless page missing');
const ws=new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
const result=new Promise((resolve,reject)=>{ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id===1)m.error?reject(new Error(m.error.message)):resolve(m.result);});});
ws.send(JSON.stringify({id:1,method:'Page.captureScreenshot',params:{format:'png',fromSurface:true,captureBeyondViewport:false}}));
await writeFile(output,Buffer.from((await result).data,'base64'));
ws.close();
