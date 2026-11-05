#!/usr/bin/env bash
# Real Identity and Pricing empty/private states, not populated journey acceptance.
set -euo pipefail
cd "$(dirname "$0")/../../.."
export CHROME_DEVTOOLS_AXI_SESSION=bt-s2-l14
export CHROME_DEVTOOLS_AXI_BROWSER_URL='http://127.0.0.1:19614'
base="${BT_BROWSER_ORIGIN:-http://127.0.0.1:3610}"
mkdir -p tests/lanes/L14/.local/browser
python3 - <<'PY'
import socket
with socket.socket() as s:s.bind(('127.0.0.1',19614))
PY
profile=$(mktemp -d "$PWD/tests/lanes/L14/.local/chrome-capture.XXXXXX")
chrome_pid=''
cleanup(){
  chrome-devtools-axi stop >/dev/null 2>&1 || true
  if [ -n "$chrome_pid" ]; then kill "$chrome_pid" 2>/dev/null || true; wait "$chrome_pid" 2>/dev/null || true; fi
  rm -rf -- "$profile"
}
trap cleanup EXIT
'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' --headless=new --disable-gpu --hide-scrollbars --no-first-run --remote-debugging-address=127.0.0.1 --remote-debugging-port=19614 --user-data-dir="$profile" about:blank > tests/lanes/L14/.local/chrome.log 2>&1 &
chrome_pid=$!
python3 - <<'PY'
import time,urllib.request
for i in range(100):
    try:
        urllib.request.urlopen('http://127.0.0.1:19614/json/version',timeout=1).close();break
    except OSError:time.sleep(.1)
else:raise RuntimeError('Owned headless Chrome did not start')
PY
for width in 1280 390; do
  chrome-devtools-axi open "$base/en/account" >/dev/null
  if [ "$width" = 390 ]; then chrome-devtools-axi emulate --viewport '390x844x3,mobile,touch' >/dev/null; else chrome-devtools-axi emulate --viewport '1280x900x1' >/dev/null; fi
  chrome-devtools-axi run <<'JS'
const origin=await page.eval(()=>location.origin);
await page.open(origin+'/en/account');
for(let i=0;i<80;i++){
 if(await page.eval(()=>!!document.querySelector('.identity-tabs')))break;
 await page.eval(()=>[...document.querySelectorAll('.identity-page button')].find(button=>button.textContent==='Sign out')?.click());
 await page.wait(100);
}
await page.eval(()=>[...document.querySelectorAll('.identity-tabs button')].find(button=>button.textContent==='Create an account').click());
await page.wait('input[name=display_name]');
const email=`sample-l14-${Date.now()}@example.invalid`,password=`Sample-review-${Date.now()}!`;
await page.eval(`()=>{for(const [name,value] of Object.entries({display_name:'Sample Quote Review',email:${JSON.stringify(email)},password:${JSON.stringify(password)}})){const input=document.querySelector('input[name='+name+']');input.value=value;}document.querySelector('.identity-form').requestSubmit();}`);
await page.wait('.identity-actions');
await page.open(origin+'/en/offers');
await page.wait('.l14-desk [data-kind=empty]');
if(!await page.eval(()=>document.querySelector('.l14-desk [data-kind=empty]')?.textContent.includes('Nothing to review yet')))throw new Error('Real Pricing empty state not reached');
console.log('Real synthetic personal buyer restored; no offer, diagnosis, payment or reservation seeded.');
JS
  for locale in en ar; do
    for theme in light dark; do
      chrome-devtools-axi eval "() => {document.cookie='bt-theme=$theme; Path=/; SameSite=Lax';return true;}" >/dev/null
      for route in offers brand-quotes repair-quotes; do
        chrome-devtools-axi open "$base/$locale/$route" >/dev/null
        chrome-devtools-axi run <<'JS' > "tests/lanes/L14/.local/browser/${route}-${width}-${locale}-${theme}.json"
await page.wait('.l14-desk [data-kind=empty]');
await page.wait(150);
const result=await page.eval(()=>({viewport:innerWidth,locale:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,heading:document.querySelector('.l14-desk h1')?.textContent,empty:document.querySelector('.l14-desk [data-kind=empty]')?.textContent,overflow:document.documentElement.scrollWidth>innerWidth,cards:[...document.querySelectorAll('.l14-desk .ui-card')].map(node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right};}),unauthorized:!!document.querySelector('.l14-desk a[href*=account]')}));
if(result.overflow||result.unauthorized||!result.empty||result.cards.some(card=>card.left< -1||card.right>result.viewport+1))throw new Error('Real private shell geometry failed: '+JSON.stringify(result));
console.log(JSON.stringify(result,null,2));
JS
        node tests/lanes/L14/capture-shot.mjs "$PWD/tests/lanes/L14/.local/browser/${route}-${width}-${locale}-${theme}.png" "$base/$locale/$route"
      done
    done
  done
done
# Capture from the SAME authenticated headless Chrome page. A separate process
# cannot inherit the isolated browser context's private cookies.
chrome-devtools-axi stop >/dev/null
python3 - <<'PY'
import json,pathlib
root=pathlib.Path('tests/lanes/L14/.local/browser')
observations=list(root.glob('*.json'))
assert len(observations)==24
for p in observations:
    data=json.loads(p.read_text());parts=p.stem.rsplit('-',3);route,width,locale,theme=parts
    assert data['viewport']==int(width),(p,data)
    assert data['locale']==locale and data['dir']==('rtl' if locale=='ar' else 'ltr'),(p,data)
    assert data['theme']==theme and data['heading'] and data['empty'] and not data['overflow'] and not data['unauthorized'],(p,data)
    assert p.with_suffix('.png').stat().st_size>1000

print('24 real empty/private shell observations and headless Chrome screenshots. No populated journey acceptance claimed.')
PY
