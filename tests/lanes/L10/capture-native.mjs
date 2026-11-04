// Pixel-only fallback for screenshot bridges that report a path without writing bytes.
// Start an isolated headless Chrome; use the browser CLI for navigation/emulation first.
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
const port=Number(process.argv[2]), output=process.argv[3];
if(!Number.isInteger(port)||port<1||port>65535||!output)throw new Error('Supply the isolated Chrome debug port and PNG path');
const pages=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const target=pages.find(page=>page.type==='page'&&/^http:\/\/(localhost|127\.0\.0\.1):3110\/(en|ar)\/customize/.test(page.url));
if(!target)throw new Error('No active local customization proof page');
const socket=new WebSocket(target.webSocketDebuggerUrl);
let sequence=0;
const pending=new Map();
socket.addEventListener('message',event=>{
  const message=JSON.parse(String(event.data)), callback=pending.get(message.id);
  if(!callback)return;
  pending.delete(message.id);clearTimeout(callback.timeout);
  if(message.error)callback.reject(new Error('Chrome capture failed'));else callback.resolve(message.result);
});
await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
function send(method,params={}) {
  const id=++sequence;
  return new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>{pending.delete(id);reject(new Error('Chrome capture timed out'));},15000);
    pending.set(id,{resolve,reject,timeout});socket.send(JSON.stringify({id,method,params}));
  });
}
try {
  const metrics=await send('Page.getLayoutMetrics');
  const viewport=metrics.cssVisualViewport;
  const capture=await send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false});
  const bytes=Buffer.from(capture.data,'base64'), path=resolve(output);
  await mkdir(dirname(path),{recursive:true});await writeFile(path,bytes);
  console.log(`Saved ${bytes.readUInt32BE(16)}x${bytes.readUInt32BE(20)} pixels; CSS viewport ${viewport.clientWidth}x${viewport.clientHeight}: ${path}`);
} finally {socket.close();}
