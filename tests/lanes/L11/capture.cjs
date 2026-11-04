// Screenshot-only fallback; chrome-devtools-axi owns interaction/acceptance checks.
// DeviceMetricsOverride avoids desktop Chrome's 500px minimum window cropping phone captures.
const {spawn} = require('node:child_process');
const {mkdirSync,readFileSync,rmSync,writeFileSync} = require('node:fs');
const {resolve} = require('node:path');
const upstream = new URL(process.env.L11_WEB_URL || 'http://127.0.0.1:3111');
if(upstream.hostname!=='127.0.0.1') throw new Error('Only the local proof server is supported');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  const output=resolve('tests/lanes/L11/evidence');mkdirSync(output,{recursive:true});
  const portFile=resolve('.venv/chrome-visual/DevToolsActivePort');
  rmSync(portFile,{force:true});
  const chrome=spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',[
    '--headless=new','--disable-gpu','--hide-scrollbars','--remote-debugging-port=0',
    `--user-data-dir=${resolve('.venv/chrome-visual')}`,'about:blank'
  ],{stdio:'ignore'});
  let socket;
  try{
    let targets;
    for(let attempt=0;attempt<50;attempt++){
      try{
        const port=readFileSync(portFile,'utf8').split('\n')[0];
        if(!/^[0-9]{1,5}$/.test(port))throw new Error('Invalid local debugging port');
        targets=await fetch(`http://127.0.0.1:${port}/json/list`).then(response=>response.json());if(targets.length)break;
      }catch{}
      await pause(100);
    }
    if(!targets?.length) throw new Error('Local screenshot browser did not start');
    socket=new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
    await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
    let sequence=0;const pending=new Map();
    socket.addEventListener('message',event=>{const data=JSON.parse(event.data);if(data.id){const task=pending.get(data.id);if(!task)return;pending.delete(data.id);data.error?task.reject(new Error(data.error.message)):task.resolve(data.result);}});
    const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
    await call('Page.enable');await call('Network.enable');
    const capture=async(name)=>{const image=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});writeFileSync(`${output}/${name}.png`,Buffer.from(image.data,'base64'));console.log(name);};
    for(const locale of ['en','ar']) for(const device of ['desktop','phone']) for(const theme of ['light','dark']){
      await call('Network.setCookie',{name:'bt-theme',value:theme,url:upstream.href,path:'/'});
      await call('Emulation.setDeviceMetricsOverride',{width:device==='phone'?390:1440,height:device==='phone'?844:1000,deviceScaleFactor:1,mobile:device==='phone'});
      await call('Page.navigate',{url:new URL(`/${locale}/services?business=00000000-0011-4000-8000-000000000001`,upstream).href});
      let ready=false;
      for(let attempt=0;attempt<60;attempt++){
        const status=await call('Runtime.evaluate',{expression:`Boolean(document.querySelector('.movement-panel input')) && document.documentElement.dataset.theme==='${theme}'`,returnByValue:true});
        if(status.result.value){ready=true;break;}await pause(100);
      }
      if(!ready)throw new Error(`Screenshot content did not load: ${locale}/${device}/${theme}`);
      await capture(`${locale}-${device}-${theme}`);
      if(device==='phone'){
        await call('Runtime.evaluate',{expression:"document.querySelector('.movement-panel').scrollIntoView({block:'start',behavior:'instant'})"});
        await capture(`${locale}-${device}-${theme}-detail`);
      }
    }
  }finally{socket?.close();chrome.kill('SIGTERM');}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
