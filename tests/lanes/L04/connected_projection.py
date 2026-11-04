"""Read-only Chrome acceptance against actual owning-service public APIs.

Never starts/seeds services or submits synthetic bids. With --wait-for-bid, place
an actual authorized bid through the contributing bidding UI while this observes.
No authentication tokens, commands or private response bodies enter the evidence.
"""
import argparse
import concurrent.futures
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import urlopen
from uuid import UUID
from browser_matrix import chrome, check


def origin(value):
    parsed=urlsplit(value)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise argparse.ArgumentTypeError('Use a service origin without credentials, path or query.')
    return value.rstrip('/')


def get(base,path):
    with urlopen(base+path,timeout=3) as response:
        check(response.headers.get('Cache-Control')=='no-store','owning public reads must not cache stale sale state')
        body=response.read(2*1024*1024+1)
        check(len(body)<=2*1024*1024,'public response body budget')
        return json.loads(body)


def canonical(catalog,auction,identifier):
    listing=get(catalog,'/v1/listings/'+identifier)
    check(listing['id']==identifier and listing['status']=='published','actual visible publication proof')
    check(listing['facts']['sale_mode']=='auction','choose an actual published auction listing')
    projection=get(catalog,'/v1/discovery/watches/'+identifier+'/auction')
    check(projection['state']=='available','canonical read projection is available')
    snapshot=projection['snapshot']
    # Public history carries its own repeatable-read snapshot. Use that binding,
    # not two unbound wall-clock requests, to compare the real provider and view.
    history=get(auction,'/v1/auctions/'+snapshot['auction_id']+'/history?limit=100')
    upstream=history['snapshot']
    check(upstream['listing_id']==identifier and upstream['revision']>=snapshot['revision'],'actual provider binding and monotone revision')
    if upstream['revision']==snapshot['revision']:
        check(Decimal(snapshot['current_price']['amount'])*100==upstream['current_minor'],'exact canonical bid price, not listing ask')
        check(snapshot['last_sequence']==upstream['accepted_sequence'] and datetime.fromisoformat(snapshot['ends_at'].replace('Z','+00:00'))==datetime.fromisoformat(upstream['ends_at'].replace('Z','+00:00')),'canonical receipt and end-time binding')
    return listing,snapshot


def wait_connected(session):
    check(chrome(session,'eval',"async () => {for(let i=0;i<60;i++){if(document.querySelector('.live-auction')?.dataset.connection==='connected')return true;await new Promise(resolve=>setTimeout(resolve,100));}return false;}"),'actual canonical auction must connect')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-url',type=origin,required=True)
    parser.add_argument('--catalog-url',type=origin,required=True)
    parser.add_argument('--auction-url',type=origin,required=True)
    parser.add_argument('--listing-id',type=UUID,required=True)
    parser.add_argument('--wait-for-bid',type=int,default=0,help='Seconds (0..120) to observe a real public bid placed separately.')
    parser.add_argument('--evidence',type=Path,default=Path(__file__).with_name('connected-evidence.json'))
    args=parser.parse_args()
    if not 0<=args.wait_for_bid<=120:parser.error('--wait-for-bid must be 0..120')
    identifier=str(args.listing_id)
    # Fixture transports must never be mistaken for the final connected demo.
    try:
        with urlopen(args.catalog_url+'/__fixture__/media',timeout=3):
            raise AssertionError('Contract fixture detected; use the actual owning Catalog runtime.')
    except HTTPError as error:
        check(error.code==404,'Catalog must not expose the opt-in fixture control namespace')
    listing,baseline=canonical(args.catalog_url,args.auction_url,identifier)
    detail=get(args.catalog_url,'/v1/discovery/watches/'+identifier)
    check(detail['sale_state']=='available','real Orders/Identity/timing composition confirms current sale availability')
    check(detail['media_state']=='available' and bool(detail['photos']),'actual published gallery and credits are readable')
    check(detail['demo']==listing['is_demo'],'sample provenance is not invented or dropped')
    evidence={'kind':'actual-owning-service-public-apis','listing_id':identifier,'sample':listing['is_demo'],'matrix':[],'observedNewPublicBid':False}
    sessions=('bt-l04-connected','bt-l04-connected-viewer')
    session=sessions[0];started={session}
    try:
        chrome(session,'open',args.web_url+'/en/watches/'+identifier)
        for width,height in ((1440,900),(390,844)):
            chrome(session,'emulate','--viewport',f'{width}x{height}x'+('3,mobile,touch' if width==390 else '1'))
            for locale in ('en','ar'):
                for theme in ('light','dark'):
                    chrome(session,'eval',f"() => {{document.cookie='bt-theme={theme}; Path=/';return true;}}")
                    chrome(session,'open',args.web_url+'/'+locale+'/watches/'+identifier)
                    wait_connected(session)
                    check(chrome(session,'eval',"async () => {const trigger=document.querySelector('.discovery-hero-photo');trigger?.scrollIntoView({block:'center'});for(let i=0;i<40;i++){if(trigger?.querySelector('img')?.naturalWidth>0&&trigger.querySelector('.discovery-photo')?.dataset.photoState==='ready')return true;await new Promise(resolve=>setTimeout(resolve,100));}return false;}"),'actual public photograph must decode')
                    measured=chrome(session,'eval',"() => ({width:innerWidth,height:innerHeight,lang:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth,clipped:[...document.querySelectorAll('.discovery-detail-copy,.live-auction')].some(e=>e.scrollWidth>e.clientWidth+1),historyRows:document.querySelectorAll('.live-auction-history li').length,sampleLabels:[...document.querySelectorAll('.notice')].map(e=>e.textContent)})")
                    check(measured['width']==width and measured['height']==height and not measured['overflow'] and not measured['clipped'],'actual desktop/phone viewport without clipped content')
                    check(measured['lang']==locale and measured['dir']==('rtl'if locale=='ar'else'ltr') and measured['theme']==theme,'actual EN/AR, direction and theme')
                    if listing['is_demo']:
                        check(('Sample listing'if locale=='en'else'إعلان تجريبي')in measured['sampleLabels'],'real sample stock is visibly labeled')
                    chrome(session,'eval',"() => {document.querySelector('.discovery-hero-photo').focus();document.querySelector('.discovery-hero-photo').click();return true;}")
                    check(chrome(session,'eval',"() => document.querySelector('.discovery-zoom').open"),'actual photograph zoom')
                    chrome(session,'press','Escape')
                    check(chrome(session,'eval',"() => !document.querySelector('.discovery-zoom').open&&document.activeElement.classList.contains('discovery-hero-photo')"),'keyboard zoom dismissal/focus return')
                    evidence['matrix'].append(measured)
        if args.wait_for_bid:
            for viewer in sessions:
                started.add(viewer)
                chrome(viewer,'open',args.web_url+'/en/watches/'+identifier)
                chrome(viewer,'emulate','--viewport','390x844x3,mobile,touch'if viewer==session else'1440x900x1')
                wait_connected(viewer)
                chrome(viewer,'eval',r"""() => {window.__l04PublicBids={};const observe=()=>{for(const row of document.querySelectorAll('.live-auction-history li')){const match=/#(\d+)/.exec(row.textContent);if(match&&!window.__l04PublicBids[match[1]])window.__l04PublicBids[match[1]]=performance.timeOrigin+performance.now();}};new MutationObserver(observe).observe(document.querySelector('.live-auction'),{subtree:true,childList:true,characterData:true});observe();return true;}""")
            _,baseline=canonical(args.catalog_url,args.auction_url,identifier)
            deadline=time.monotonic()+args.wait_for_bid;bid=None
            print('Two viewers ready. Place an actual authorized public bid through the bidding UI.',flush=True)
            while time.monotonic()<deadline:
                history=get(args.auction_url,'/v1/auctions/'+baseline['auction_id']+'/history?after_sequence='+str(baseline['last_sequence'])+'&limit=100')
                if history['items']:
                    bid=history['items'][0];break
                time.sleep(.4)
            check(bid is not None,'no actual new public bid observed; quiet private receipt changes do not count')
            def observed(viewer):
                return viewer,chrome(viewer,'eval',f"async () => {{for(let i=0;i<40;i++){{const instant=window.__l04PublicBids['{bid['sequence']}'];if(instant)return {{sequence:{bid['sequence']},observedAt:instant}};await new Promise(resolve=>setTimeout(resolve,100));}}return null;}}")
            with concurrent.futures.ThreadPoolExecutor(max_workers=2)as pool:
                observations=dict(pool.map(observed,sessions))
            accepted_ms=datetime.fromisoformat(bid['received_at'].replace('Z','+00:00')).timestamp()*1000
            for value in observations.values():
                check(value is not None,'both viewers must observe the real canonical public bid')
                value['serverReceiptToDisplayMs']=round(value['observedAt']-accepted_ms)
                check(0<=value['serverReceiptToDisplayMs']<2000,'same-host server-receipt-to-display target (not a receipt acknowledgement latency)')
            evidence.update(observedNewPublicBid=True,twoViewerActual=observations)
        _,final=canonical(args.catalog_url,args.auction_url,identifier)
        evidence.update(revision=final['revision'],sequence=final['last_sequence'],end_version=final['end_version'])
        args.evidence.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'matrix':len(evidence['matrix']),'observedNewPublicBid':evidence['observedNewPublicBid']}))
    finally:
        for viewer in sorted(started):
            chrome(viewer,'stop')


if __name__=='__main__':main()
