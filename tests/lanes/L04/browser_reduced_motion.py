"""Real reduced-motion CSS proof against the opt-in browser contract fixture."""
import json
import os
from pathlib import Path
from browser_matrix import chrome, check
from fixture_data import listing_id

session=f'bt-l04-motion-{os.getpid()}'
previous=os.environ.get('CHROME_DEVTOOLS_AXI_CHROME_ARGS')
os.environ['CHROME_DEVTOOLS_AXI_CHROME_ARGS']=((previous or '')+' --force-prefers-reduced-motion').strip()
try:
    chrome(session,'open','http://localhost:3044/en/watches/'+listing_id())
    chrome(session,'emulate','--viewport','390x844x3,mobile,touch')
    result=chrome(session,'eval',"async () => {for(let i=0;i<40;i++){const bid=document.querySelector('.live-auction-history li');if(bid)return {width:innerWidth,height:innerHeight,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,animation:getComputedStyle(bid).animationName,announcement:document.querySelector('.live-auction .sr-only')?.getAttribute('role')};await new Promise(resolve=>setTimeout(resolve,100));}return null;}")
    print(json.dumps(result))
    check(result and result['width']==390 and result['height']==844,'actual phone viewport')
    check(result['reduced'] and result['animation']=='none','reduced-motion bid highlight must be disabled')
    check(result['announcement']=='status','accepted canonical changes must retain an accessible announcement')
    Path(__file__).with_name('motion-evidence.json').write_text(json.dumps({'kind':'contract-fixture-not-final-connected-demo',**result},indent=2)+'\n')
finally:
    try:chrome(session,'stop')
    finally:
        if previous is None:os.environ.pop('CHROME_DEVTOOLS_AXI_CHROME_ARGS',None)
        else:os.environ['CHROME_DEVTOOLS_AXI_CHROME_ARGS']=previous
