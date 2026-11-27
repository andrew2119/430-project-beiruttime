// Headless Chrome artifact capture only. Interaction stays in chrome-devtools-axi.
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
const destination=path.resolve(process.argv[2]??'');
const expected=process.argv[3];
const allowed=['browser','offers-browser'].map(name=>path.resolve(`tests/lanes/L14/.local/${name}`)+path.sep);
const origin=expected?new URL(expected).origin:'';
const port=process.env.BT_L14_CAPTURE_PORT??'19614';
if(!allowed.some(root=>destination.startsWith(root))||!destination.endsWith('.png')||!['http://127.0.0.1:3610','http://127.0.0.1:3640'].includes(origin)||!['19614','19615'].includes(port))throw new Error('Screenshot must name an owned proof page, port and path');
const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const target=targets.find(entry=>entry.type==='page'&&entry.url===expected);
if(!target)throw new Error('Owned headless proof page is not open');
const socket=new WebSocket(target.webSocketDebuggerUrl);
const timer=setTimeout(()=>{socket.close();throw new Error('Screenshot deadline');},10000);
await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
const image=new Promise((resolve,reject)=>socket.addEventListener('message',event=>{const response=JSON.parse(event.data);if(response.id===1){if(response.error)reject(new Error('Screenshot failed'));else resolve(response.result.data);}}));
socket.send(JSON.stringify({id:1,method:'Page.captureScreenshot',params:{format:'png',fromSurface:true,captureBeyondViewport:false}}));
await writeFile(destination,Buffer.from(await image,'base64'));
clearTimeout(timer);socket.close();
