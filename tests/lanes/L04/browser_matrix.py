"""Chrome contract-fixture evidence. Uses chrome-devtools-axi, not a DOM emulator.

Run only with browser_fixture.py on localhost:8144 and the production web build
on localhost:3044. These tests do not claim connected L03/L05 acceptance.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from fixture_data import listing_id

ROOT = Path(__file__).resolve().parent

def chrome(session, *args):
    result = subprocess.run(['chrome-devtools-axi',*args],env={**os.environ,'CHROME_DEVTOOLS_AXI_SESSION':session},text=True,capture_output=True,check=True,timeout=30)
    if args[0] != 'eval': return result.stdout
    raw=result.stdout.split('result:',1)[1].split('\nhelp[',1)[0].strip()
    value=json.loads(raw)
    return json.loads(value) if isinstance(value,str) else value


def mutate(path):
    request=urllib.request.Request('http://localhost:8144/__fixture__/'+path,method='POST',headers={'X-L04-Fixture-Key':'contract-proof-only'})
    with urllib.request.urlopen(request) as response: return json.load(response)


def check(condition, message):
    if not condition: raise AssertionError(message)


def main():
    evidence={'kind':'contract-fixture-not-final-connected-demo','matrix':[]}
    session='bt-l04'
    chrome(session,'open','http://localhost:3044/en/watches')
    for width,height in ((1440,900),(390,844)):
        chrome(session,'emulate','--viewport',f'{width}x{height}x'+('3,mobile,touch' if width<=850 else '1'))
        for locale in ('en','ar'):
            for theme in ('light','dark'):
                chrome(session,'eval',f"() => {{document.cookie='bt-theme={theme}; Path=/';return true;}}")
                for page in ('watches',f'watches/{listing_id()}'):
                    chrome(session,'open',f'http://localhost:3044/{locale}/{page}')
                    time.sleep(.25)
                    if page=='watches':chrome(session,'eval',"() => {document.querySelector('.discovery-watch-card')?.scrollIntoView({block:'start'});return true;}")
                    check(chrome(session,'eval',"async () => {for(let i=0;i<40;i++){const visible=[...document.querySelectorAll('.discovery-photo[data-has-photo=\"true\"]')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.top<innerHeight&&r.bottom>0;});if(visible.every(e=>e.dataset.photoState==='ready'))return true;await new Promise(resolve=>setTimeout(resolve,100));}return false;}"),'visible public photographs settle after bounded retries')
                    measured=chrome(session,'eval',"""() => ({lang:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth,clipped:[...document.querySelectorAll('.discovery-page,.discovery-watch-card,.discovery-card-copy,.discovery-detail-copy,.live-auction')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&(r.x<0||r.right>innerWidth+1||e.scrollWidth>e.clientWidth+1);}).map(e=>e.className),heading:document.querySelector('h1')?.textContent,cards:document.querySelectorAll('.discovery-watch-card').length,images:[...document.querySelectorAll('.discovery-photo[data-has-photo=\"true\"]')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.top<innerHeight&&r.bottom>0;}).every(e=>e.dataset.photoState==='ready'),live:document.querySelector('.live-auction')?.dataset.connection,photoTarget:document.querySelector('.discovery-hero-photo')?.getBoundingClientRect().width})""")
                    check(measured['lang']==locale and measured['dir']==('rtl' if locale=='ar' else 'ltr'),'locale/direction')
                    check(measured['width']==width and measured['height']==height,'actual emulated viewport must equal the requested size')
                    check(measured['theme']==theme and not measured['overflow'] and not measured['clipped'],'theme or clipped horizontal content')
                    check(measured['images'],'public image decode')
                    if page=='watches': check(measured['cards']==12,'bounded first page')
                    else:
                        check(measured['live']=='connected','canonical fixture must connect')
                        check(measured['photoTarget']>=44,'gallery target')
                        chrome(session,'eval',"() => {const trigger=document.querySelector('.discovery-hero-photo');trigger.focus();trigger.click();return document.querySelector('.discovery-zoom').open;}")
                        check(chrome(session,'eval',"() => document.querySelector('.discovery-zoom').open"),'zoom dialog')
                        chrome(session,'press','Escape')
                        check(chrome(session,'eval',"() => !document.querySelector('.discovery-zoom').open && document.activeElement.classList.contains('discovery-hero-photo')"),'Escape restores gallery focus')
                    evidence['matrix'].append({**measured,'page':page,'viewport':[width,height]})
                    (ROOT/'browser-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    chrome(session,'open','http://localhost:3044/en/watches?sort=ending_soon')
    check(chrome(session,'eval',"() => document.querySelectorAll('.discovery-watch-card').length===11"),'ending-soon uses the owning timing feed and current stock, not publication dates')
    evidence['canonicalEndingFeed']=True
    for query,selector in (('q=%D8%B1%D9%88%D9%84%D9%83%D8%B3&model=%D9%A3%D9%A6','.discovery-watch-card'),('q=not-a-real-match','.discovery-message'),('min_minor=%D9%A2&max_minor=%D9%A1','[role=alert]')):
        chrome(session,'open','http://localhost:3044/ar/watches?'+query)
        check(chrome(session,'eval',f"() => !!document.querySelector('{selector}')"),'Arabic/empty/range state')
    chrome(session,'open','http://localhost:3044/en/watches/nonpublic-reference')
    check(chrome(session,'eval',"() => document.querySelector('h1')?.textContent==='This watch is not available to view.'"),'private reference remains missing')

    evidence['disclosureStates']=[]
    for locale in ('en','ar'):
        for identifier, expected in ((listing_id(1),'REF-TEST-36'),(listing_id(2),'This business was onboarded by the platform.' if locale=='en' else 'هذا النشاط التجاري معتمد على المنصة.'),(listing_id(3),'Business onboarding could not be confirmed.' if locale=='en' else 'تعذر تأكيد اعتماد النشاط التجاري.')):
            chrome(session,'open',f'http://localhost:3044/{locale}/watches/{identifier}')
            check(chrome(session,'eval',f'() => document.querySelector("main").textContent.includes({json.dumps(expected)})'),'modified/business disclosure state')
            evidence['disclosureStates'].append({'locale':locale,'id':identifier})

    evidence['edgeViewports']=[]
    for width,height in ((320,568),(850,900),(851,900)):
        chrome(session,'emulate','--viewport',f'{width}x{height}x1'+(',mobile,touch' if width<=850 else ''))
        chrome(session,'open','http://localhost:3044/ar/watches/'+listing_id(4))
        measure=chrome(session,'eval',"() => ({width:innerWidth,clipped:[...document.querySelectorAll('.discovery-page,.discovery-detail-copy,.discovery-sale')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&(r.x<0||r.right>innerWidth+1||e.scrollWidth>e.clientWidth+1);}).map(e=>e.className)})")
        check(measure['width']==width and not measure['clipped'],'maximum exact price must fit narrow/breakpoint viewports')
        evidence['edgeViewports'].append(measure)

    for viewer in ('bt-l04','bt-l04-viewer'):
        chrome(viewer,'open','http://localhost:3044/en/watches/'+listing_id())
        chrome(viewer,'emulate','--viewport','390x844x3,mobile,touch' if viewer=='bt-l04' else '1440x900x1')
        chrome(viewer,'eval',r"""() => { window.__l04Updates={};const observe=()=>{const text=document.querySelector('.live-auction-history li')?.textContent??'';const match=/#(\d+)/.exec(text);if(match&&!window.__l04Updates[match[1]])window.__l04Updates[match[1]]=performance.timeOrigin+performance.now();};new MutationObserver(observe).observe(document.querySelector('.live-auction'),{subtree:true,childList:true,characterData:true});observe();return true;}""")
    ack=mutate('advance');ack_time=time.time()*1000
    time.sleep(1.25)
    def observe(viewer):
        return viewer,chrome(viewer,'eval',f"() => ({{sequence:{ack['sequence']},observedAt:window.__l04Updates['{ack['sequence']}'],history:document.querySelectorAll('.live-auction-history li').length}})")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        views=dict(pool.map(observe,('bt-l04','bt-l04-viewer')))
    for value in views.values():
        check(value.get('observedAt') is not None and value['observedAt']-ack_time<2000,'two-viewer fixture visibility target')
        value['latencyMs']=round(value['observedAt']-ack_time)
    evidence['twoViewerFixture']=views
    for _ in range(6): ack=mutate('advance')
    time.sleep(1.5)
    check(chrome(session,'eval',f"() => !!window.__l04Updates['{ack['sequence']}']"),'gap recovery from full snapshot')
    before=chrome(session,'eval',"() => document.querySelector('.live-auction-stats strong bdi')?.textContent")
    chrome(session,'eval',"() => {Date.now=()=>1;return true;}")
    time.sleep(1.25)
    after=chrome(session,'eval',"() => document.querySelector('.live-auction-stats strong bdi')?.textContent")
    check(before is not None and after is not None,'server countdown survives wrong client wall clock')
    evidence['clock']={'before':before,'after':after,'clientDateNow':1}
    mutate('availability/unavailable');time.sleep(2)
    check(chrome(session,'eval',"() => document.querySelector('.live-auction').dataset.connection==='reconnecting' && document.querySelector('.live-auction-stats strong').textContent==='—'"),'unavailable must hide stale price')
    mutate('availability/available');time.sleep(1.25)
    chrome(session,'eval',"() => {window.dispatchEvent(new Event('online'));return true;}")
    check(chrome(session,'eval',"async () => {for(let i=0;i<60;i++){if(document.querySelector('.live-auction')?.dataset.connection==='connected')return true;await new Promise(resolve=>setTimeout(resolve,100));}return false;}"),'reconnect canonical recovery')
    evidence['gapAndReconnect']=True
    mutate('media/unavailable')
    chrome(session,'open','http://localhost:3044/en/watches/'+listing_id())
    time.sleep(2.5)
    check(chrome(session,'eval',"() => document.querySelector('.discovery-photo').dataset.photoState==='unavailable' && document.querySelector('.discovery-photo').textContent.includes('temporarily unavailable')"),'failed photograph must not pretend no public photo exists')
    request=urllib.request.Request('http://localhost:8144/__fixture__/media',headers={'X-L04-Fixture-Key':'contract-proof-only'})
    with urllib.request.urlopen(request) as response: media=json.load(response)
    check(0<media['requests']<=12,'media retries must remain bounded')
    mutate('media/available')
    chrome(session,'open','http://localhost:3044/en/watches/'+listing_id())
    check(chrome(session,'eval',"async () => {for(let i=0;i<40;i++){if(document.querySelector('.discovery-photo')?.dataset.photoState==='ready')return true;await new Promise(resolve=>setTimeout(resolve,100));}return false;}"),'public photograph recovery')
    evidence['mediaFailure']={'requests':media['requests'],'honestUnavailable':True,'recovered':True}
    mutate('orders/unavailable')
    chrome(session,'open','http://localhost:3044/en/watches/'+listing_id())
    check(chrome(session,'eval',"() => document.querySelector('.discovery-sale').textContent.includes('Sale availability unconfirmed') && !!document.querySelector('.discovery-gallery')"),'publication must not fake current Orders availability')
    mutate('orders/available')
    mutate('credits/unavailable')
    chrome(session,'open','http://localhost:3044/en/watches/'+listing_id())
    check(chrome(session,'eval',"() => document.querySelector('.discovery-gallery').textContent.includes('Photograph temporarily unavailable') && !document.querySelector('.discovery-gallery img')"),'unavailable attribution must not display uncredited photos or claim no photo exists')
    mutate('credits/available')
    chrome(session,'open','http://localhost:3044/en/watches/'+listing_id(5))
    check(chrome(session,'eval',"() => document.querySelector('.discovery-sale').textContent.includes('Listing price not stated') && document.querySelector('.discovery-sale').textContent.includes('Offers considered')"),'offer without price is not a fabricated zero-price purchase')
    chrome(session,'open','http://localhost:3044/en/watches/'+listing_id(7))
    check(chrome(session,'eval',"() => document.querySelector('.discovery-sale').textContent.includes('Awaiting auction opening')"),'missing canonical auction is explicitly not started')
    evidence['currentAuthorityAndNullPrice']=True
    (ROOT/'browser-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'matrix':len(evidence['matrix']),'twoViewerFixtureLatencyMs':{key:value['latencyMs'] for key,value in views.items()},'gapAndReconnect':True}))

if __name__=='__main__':main()
