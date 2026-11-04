// Headless artifact capture only; browser interactions use chrome-devtools-axi.
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
const destination=path.resolve(process.argv[2]??'');
const allowed=path.resolve('tests/lanes/L07/.runtime')+path.sep;
if(!destination.startsWith(allowed)||!destination.endsWith('.png'))throw new Error('Screenshot must stay in owned ignored evidence');
const targets=await(await fetch('http://127.0.0.1:19607/json/list')).json();
const target=targets.find(entry=>entry.type==='page'&&entry.url.startsWith('http://localhost:3077/'));
if(!target)throw new Error('No owned L07 proof page');
const socket=new WebSocket(target.webSocketDebuggerUrl);
const timer=setTimeout(()=>{socket.close();throw new Error('Screenshot deadline');},10000);
await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
const image=new Promise((resolve,reject)=>socket.addEventListener('message',event=>{const response=JSON.parse(event.data);if(response.id===1){if(response.error)reject(new Error('Screenshot failed'));else resolve(response.result.data);}}));
socket.send(JSON.stringify({id:1,method:'Page.captureScreenshot',params:{format:'png',fromSurface:true,captureBeyondViewport:false}}));
await writeFile(destination,Buffer.from(await image,'base64'));
clearTimeout(timer);socket.close();console.log(destination);
