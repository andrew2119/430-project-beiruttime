"""Opt-in real Chrome proof of public/current-policy and guarded seller tabs.

Uses real Auction handlers/isolated PostgreSQL with labeled synthetic provider
fixtures; this is NOT connected Pricing/Orders/Identity acceptance.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile

import httpx
import pytest
import uvicorn

pytestmark=pytest.mark.skipif(os.environ.get('BT_L12_BROWSER')!='1',reason='Opt-in host Chrome proof; run under the serialized heavy slot')
ROOT=next((p for p in Path(__file__).resolve().parents if (p/'compose.yaml').is_file()),Path('/host-only'))
CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


async def command(*args,env=None,stdin=None):
    process=await asyncio.create_subprocess_exec(*args,env=env,stdin=asyncio.subprocess.PIPE if stdin else None,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
    output=(await process.communicate(stdin.encode() if stdin else None))[0].decode()
    assert process.returncode==0,output
    return output


async def screenshots(origin,directory):
    import websockets
    with tempfile.TemporaryDirectory(prefix='l12-chrome-',dir=directory) as profile:
        process=await asyncio.create_subprocess_exec(CHROME,'--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run','--no-default-browser-check','--disable-extensions','--disable-background-networking',f'--user-data-dir={profile}','--remote-debugging-port=3414','about:blank',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        try:
            async with httpx.AsyncClient() as client:
                for _ in range(60):
                    try:
                        pages=[page for page in (await client.get('http://127.0.0.1:3414/json/list')).json() if page.get('type')=='page']
                        if pages:break
                    except httpx.HTTPError:pass
                    await asyncio.sleep(.2)
            async with websockets.connect(pages[0]['webSocketDebuggerUrl']) as socket:
                sequence=0
                async def cdp(method,params=None):
                    nonlocal sequence
                    sequence+=1
                    id=sequence
                    await socket.send(json.dumps({'id':id,'method':method,'params':params or {}}))
                    while True:
                        data=json.loads(await socket.recv())
                        if data.get('id')==id:
                            assert 'error' not in data,data
                            return data['result']
                await cdp('Page.enable')
                for width in [1280,390]:
                    await cdp('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':width==390})
                    for locale in ['en','ar']:
                        for theme in ['light','dark']:
                            await cdp('Network.setCookie',{'name':'bt-theme','value':theme,'url':origin,'path':'/'})
                            await cdp('Page.navigate',{'url':f'{origin}/{locale}/auction-policy'})
                            for _ in range(100):
                                state=await cdp('Runtime.evaluate',{'expression':"({loaded:!!document.querySelector('.auction-policy-panel'),width:innerWidth,theme:document.documentElement.dataset.theme,locale:document.documentElement.lang})",'returnByValue':True})
                                value=state.get('result',{}).get('value',{})
                                if value.get('loaded') and value.get('theme')==theme and value.get('locale')==locale:break
                                await asyncio.sleep(.1)
                            assert value.get('loaded') and value['width']==width and value['theme']==theme and value['locale']==locale,value
                            await asyncio.sleep(.7)
                            image=await cdp('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                            (directory/f'policy-{locale}-{theme}-{width}.png').write_bytes(base64.b64decode(image['data']))
        finally:
            process.terminate()
            await process.wait()


async def test_real_policy_tabs(api):
    for port in [3412,3413,3414]:
        check=subprocess.run(['lsof','-nP',f'-iTCP:{port}','-sTCP:LISTEN'],capture_output=True)
        assert check.returncode==1,f'Port {port} is not free'
    client,app,fixture,id=api
    origin='http://127.0.0.1:3412'
    directory=ROOT/'artifacts/l12-browser'
    directory.mkdir(parents=True,exist_ok=True)
    container=os.environ.get('BT_L12_CONTAINER_BROWSER')=='1'
    server=None
    service=None
    if not container:
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=3413,log_level='warning',lifespan='off'))
        service=asyncio.create_task(server.serve())
    env={**os.environ,'AUCTION_API_URL':'http://127.0.0.1:3413','BT_ALLOWED_WEB_ORIGINS':origin,'BT_PUBLIC_WEB_ORIGINS':origin,'NEXT_TELEMETRY_DISABLED':'1','CHROME_DEVTOOLS_AXI_SESSION':'bt-s2-l12'}
    for name in ['IDENTITY','CATALOG','PRICING','ORDERS','ELIGIBILITY','TRUST','COMMUNICATIONS','SERVICE_OPERATIONS']:env[name+'_API_URL']='http://127.0.0.1:3499'
    web=None
    log=(directory/'next.log').open('w')
    compose=['docker','compose','-f',str(ROOT/'tests/lanes/L12/compose.proof.yaml'),'-p','bt-s2-l12-proof-'+str(os.getpid())]
    if container:
        env.update({'BT_L12_AUCTION_SOURCE':str(ROOT/'services/auction/runtime/service_app'),'BT_L12_AUCTION_MODULES':str(ROOT/'services/auction/modules'),'BT_L12_DOMAIN_CONTRACTS':str(ROOT/'artifacts/l12-contracts')})
        from urllib.parse import urlparse, urlunparse
        url=urlparse(app.state.settings.database_url)
        env['BT_L12_DATABASE_URL']=urlunparse(url._replace(netloc=url.netloc.replace('127.0.0.1:'+str(url.port),'postgres:5432')))
    try:
        if container:
            await command(*compose,'up','-d','--no-build','--wait','--wait-timeout','60',env=env)
        else:
            web=await asyncio.create_subprocess_exec('pnpm','exec','next','dev','--hostname','127.0.0.1','--port','3412',cwd=ROOT/'web',env=env,stdout=log,stderr=log,start_new_session=True)
        async with httpx.AsyncClient(timeout=60) as browser:
            for _ in range(100):
                try:
                    response=await browser.get(origin+'/en/auction-policy')
                    if response.status_code==200:break
                except httpx.HTTPError:pass
                await asyncio.sleep(.3)
            assert response.status_code==200
        await command('chrome-devtools-axi','open',origin+'/en/auction-policy',env=env)
        script=(ROOT/'tests/lanes/L12/browser-matrix.js').read_text()
        for width in [1280,390]:
            await command('chrome-devtools-axi','emulate','--viewport',f'{width}x844x3'+(',mobile,touch' if width==390 else ''),env=env)
            result=await command('chrome-devtools-axi','run',env=env,stdin=f'const WIDTH={width};\n'+script)
            (directory/f'dom-{width}.json').write_text(result)
        await command('chrome-devtools-axi','stop',env=env)
        await screenshots(origin,directory)
        (directory/'scope.txt').write_text('16 DOM cases; 8 actual headless Chrome screenshots. Real Auction/isolated PostgreSQL operations with synthetic provider fixtures. Seller unavailable boundary checked, not a connected authenticated seller mutation. No connected commercial/payment acceptance claimed.\n')
    finally:
        await command('chrome-devtools-axi','stop',env=env)
        if web and web.returncode is None:
            import signal
            os.killpg(web.pid,signal.SIGTERM)
            await web.wait()
        log.close()
        if container:await command(*compose,'stop',env=env)
        if server:
            server.should_exit=True
            await service
