"""Headless Chrome evidence with a real, separate Identity refresh lineage."""
import asyncio
import base64
import json
from pathlib import Path
import tempfile
import httpx
import websockets

CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


async def screenshots(origin,directory,listing,refresh_cookie):
    assert refresh_cookie,'Actual Identity login cookie is required'
    with tempfile.TemporaryDirectory(prefix='l12-live-chrome-',dir=directory) as profile:
        process=await asyncio.create_subprocess_exec(CHROME,'--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run',
            '--no-default-browser-check','--disable-extensions','--disable-background-networking',f'--user-data-dir={profile}',
            '--remote-debugging-port=3414','about:blank',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
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
                        result=json.loads(await socket.recv())
                        if result.get('id')==id:
                            assert 'error' not in result,result
                            return result['result']
                await cdp('Page.enable')
                # Set ONCE. Identity rotates this cookie on refresh; replaying the
                # original cookie on each theme would revoke the actual lineage.
                await cdp('Network.setCookie',{'name':'bt_refresh','value':refresh_cookie,'url':origin,'path':'/','httpOnly':True,'sameSite':'Strict'})
                for width in [1280,390]:
                    await cdp('Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,'deviceScaleFactor':1,'mobile':width==390})
                    for locale in ['en','ar']:
                        for theme in ['light','dark']:
                            await cdp('Network.setCookie',{'name':'bt-theme','value':theme,'url':origin,'path':'/'})
                            await cdp('Page.navigate',{'url':f'{origin}/{locale}/auction-policy?listing_id={listing}'})
                            for _ in range(150):
                                result=await cdp('Runtime.evaluate',{'expression':"({loaded:!!document.querySelector('.auction-policy-panel dd'),purchase:!!document.querySelector('.auction-policy-form, a[href*=\"/checkout?order_id=\"]'),width:innerWidth,theme:document.documentElement.dataset.theme,locale:document.documentElement.lang,overflow:document.documentElement.scrollWidth>innerWidth+1})",'returnByValue':True})
                                value=result.get('result',{}).get('value',{})
                                if value.get('loaded') and value.get('theme')==theme and value.get('locale')==locale:break
                                await asyncio.sleep(.2)
                            assert value.get('loaded') and value['width']==width and not value['overflow'] and not value['purchase'],value
                            await asyncio.sleep(.5)
                            image=await cdp('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                            (directory/f'fixed-policy-{locale}-{theme}-{width}.png').write_bytes(base64.b64decode(image['data']))
        finally:
            process.terminate()
            await process.wait()
