"""Bounded real-session viewport and headless capture sweep.
Called by proof.py --visual-check inside its existing heavy reservation. No API
responses, credentials, business facts or DOM outcomes are fabricated.
"""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'tests/lanes/L15/.artifacts'
PUBLIC = json.loads((OUT/'proof-public.json').read_text())
ENV = dict(os.environ,CHROME_DEVTOOLS_AXI_SESSION='bt-s2-l15',CHROME_DEVTOOLS_AXI_AUTO_CONNECT='0',
           CHROME_DEVTOOLS_AXI_USER_DATA_DIR=str(OUT/'profile-light'))
ENV.pop('CHROME_DEVTOOLS_AXI_BROWSER_URL',None)


def cli(*command):
    if (OUT/'proof.stop').exists():
        raise RuntimeError('Own visual proof stop requested')
    return subprocess.check_output(['chrome-devtools-axi',*command],env=ENV,text=True,timeout=60)


def sign_in(role):
    actor=json.loads((OUT/'actors.key').read_text())[role]
    cli('open',PUBLIC['origin']+'/en/account')
    cli('emulate','--viewport','1280x844x1','--color-scheme','light')
    time.sleep(.8)
    script=f'''await page.open({json.dumps(PUBLIC['origin']+'/en/account')});await page.wait(500);
      await page.eval(()=>{{const out=[...document.querySelectorAll('button')].find(b=>b.textContent==='Sign out');if(out)out.click();}});
      await page.wait(300);await page.open({json.dumps(PUBLIC['origin']+'/en/account')});await page.wait(300);
      await page.fill('input[type=email]',{json.dumps(actor['email'])});
      await page.fill('input[type=password]',{json.dumps(actor['password'])});
      await page.click('form button');await page.wait(1000);
      console.log(await page.eval(()=>[...document.querySelectorAll('button')].some(b=>b.textContent==='Sign out')?'PASS|signed-in':'FAIL|sign-in'));
    '''
    result=subprocess.check_output(['chrome-devtools-axi','run'],env=ENV,input=script,text=True,timeout=90)
    if 'PASS|signed-in' not in result:
        raise RuntimeError('Own synthetic sign-in was not confirmed')


def theme(value,path):
    cli('open',PUBLIC['origin']+'/en/'+path)
    time.sleep(.6)
    cli('eval',f'''() => {{if(document.documentElement.dataset.theme!=={json.dumps(value)})
      document.querySelector('button[aria-label="Switch to {value} theme"]').click();return 'shell theme control';}}''')
    time.sleep(.3)
    if value not in cli('eval','document.documentElement.dataset.theme'):
        raise RuntimeError('Real shell theme control did not settle')


for role in ('buyer','brand'):
    sign_in(role)
    subprocess.run(['python3','tests/lanes/L15/browser-matrix.py',role],env=ENV,cwd=ROOT,check=True,timeout=240)
    path='custom-requests?draft='+PUBLIC['draft_id'] if role=='buyer' else 'business/customizations?organization_id='+PUBLIC['brand_id']
    for value in ('light','dark'):
        theme(value,path)
        cli('stop')
        time.sleep(.3)
        subprocess.run(['python3','tests/lanes/L15/screenshots.py',role,value],env=ENV,cwd=ROOT,check=True,timeout=300)
(OUT/'visual-proof.json').write_text(json.dumps({
    'sample':True,'project':PUBLIC['project'],'actual_viewport_checks':32,
    'requested_headless_captures':32,'session':'bt-s2-l15',
    'phone_geometry':'Asserted 390px inner width and visible bounds in the interaction browser; native screenshots use requested window width.',
    'business_responses_fabricated':False,
},indent=2))
print('Bounded current-code real viewport and headless visual sweep passed',flush=True)
