#!/usr/bin/env bash
# Run after signing in with a synthetic buyer through the real Account page.
set -euo pipefail
cd "$(dirname "$0")/../../.."
export CHROME_DEVTOOLS_AXI_SESSION="${CHROME_DEVTOOLS_AXI_SESSION:-bt-l07}"
base="${BT_BROWSER_ORIGIN:-http://localhost:3077}"
mkdir -p tests/lanes/L07/.runtime/browser
for width in 1440 390; do
  if [ "$width" = 390 ]; then chrome-devtools-axi emulate --viewport '390x844x3,mobile,touch' >/dev/null; else chrome-devtools-axi emulate --viewport '1440x900x1' >/dev/null; fi
  # Device emulation may change a browser's session binding. Create a fresh, real
  # synthetic buyer per viewport; this also proves prior-user private cache purge.
  chrome-devtools-axi open "$base/en/account" >/dev/null
  chrome-devtools-axi run <<'JS'
await page.eval(()=>{document.querySelector('input[name=email]').value=`sample-l07-matrix-${Date.now()}@example.invalid`;document.querySelector('input[name=password]').value=`Sample-validation-${Date.now()}!`;document.querySelector('form button').click();});
let status='';for(let i=0;i<50;i++){await page.wait(100);status=await page.eval(()=>document.querySelector('[role=status]')?.textContent??'');if(status)break;}
if(!status.includes('Signed in'))throw new Error('Real matrix buyer registration failed');
await page.open((await page.eval(()=>location.origin))+'/en/prices');
for(let i=0;i<50;i++){if(await page.eval(()=>!!document.querySelector('input[name=subject]')))break;await page.wait(100);}
await page.eval(()=>{const set=(name,value)=>{const input=document.querySelector(`input[name=${name}]`);Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));};set('subject','00000000-0000-4000-8000-000000005000');set('price','٥٠٠٠٫٠٠');});
await page.wait(50);
await page.eval(()=>document.querySelector('.l07-form button[type=submit]').click());
for(let i=0;i<50;i++){if(await page.eval(()=>!!document.querySelector('.l07-fees')))break;await page.wait(100);}
if(!await page.eval(()=>document.querySelector('.l07-fees')?.textContent.includes('5,150.00 USD')))throw new Error('Matrix fee fixture did not persist');
await page.open((await page.eval(()=>location.origin))+'/en/buying');
for(let i=0;i<50;i++){if(await page.eval(()=>!!document.querySelector('input[name=draft_subject]')))break;await page.wait(100);}
await page.eval(()=>{const set=(name,value)=>{const input=document.querySelector(`input[name=${name}]`);Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));};set('draft_subject','00000000-0000-4000-8000-000000005000');set('draft_amount','٤٨٠٠٫٠٠');});
await page.wait(50);
await page.eval(()=>document.querySelector('input[name=draft_subject]').closest('form').querySelector('button').click());
for(let i=0;i<50;i++){if(await page.eval(()=>!!document.querySelector('.l07-history .card')))break;await page.wait(100);}
if(!await page.eval(()=>document.querySelector('.l07-history .card')?.textContent.includes('4,800.00 USD')))throw new Error('Matrix draft did not persist');
console.log('Fresh real sample buyer and retained quote/draft prepared');
JS
  for locale in en ar; do
    for theme in light dark; do
      chrome-devtools-axi open "$base/$locale/prices" >/dev/null
      chrome-devtools-axi eval "() => { document.cookie='bt-theme=$theme; Path=/; SameSite=Lax'; return true; }" >/dev/null
      for route in prices inbox buying; do
        chrome-devtools-axi open "$base/$locale/$route" >/dev/null
        chrome-devtools-axi run <<'JS' > "tests/lanes/L07/.runtime/browser/${route}-${width}-${locale}-${theme}.json"
await page.wait('.l07');
await page.wait('.l07-form,.l07-inbox-pref');
await page.wait(500);
const tappable=await page.eval(()=>{const actions=[...document.querySelectorAll('.l07 button,.l07 a')].filter(node=>!node.hasAttribute('disabled'));const last=actions.at(-1);if(!last)return false;last.scrollIntoView({block:'center'});const r=last.getBoundingClientRect();const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return hit===last||last.contains(hit);});
const result=await page.eval(()=>({
  lang:document.documentElement.lang,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,
  heading:document.querySelector('.l07 h1')?.textContent,
  viewport:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,
  cards:[...document.querySelectorAll('.l07 .card')].map(node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width};}),
  authenticated:!!document.querySelector('.l07-form,.l07-inbox-pref'),
  inputs:[...document.querySelectorAll('.l07 input')].map(node=>({font:parseFloat(getComputedStyle(node).fontSize),height:node.getBoundingClientRect().height})),
  actions:[...document.querySelectorAll('.l07 button,.l07 a')].filter(node=>!node.hasAttribute('disabled')).map(node=>{const r=node.getBoundingClientRect();return {width:r.width,height:r.height};})
}));
result.lastActionTappable=tappable;
if(!result.authenticated||!tappable||result.overflow||result.cards.some(card=>card.left < -1||card.right>result.viewport+1)||result.actions.some(action=>action.width<43.5||action.height<43.5)||result.inputs.some(input=>input.font<16&&result.viewport<=850)) throw new Error('L07 geometry failed: '+JSON.stringify(result));
console.log(JSON.stringify(result,null,2));
JS
        chrome-devtools-axi screenshot "tests/lanes/L07/.runtime/browser/${route}-${width}-${locale}-${theme}.png" >/dev/null
      done
    done
  done
done
python3 - <<'PY'
import json,pathlib
paths=list(pathlib.Path('tests/lanes/L07/.runtime/browser').glob('*.json'))
assert len(paths)==24
for path in paths:
    route,width,locale,theme=path.stem.split('-')
    data=json.loads(path.read_text())
    assert data['viewport']==int(width),(path,data)
    assert data['lang']==locale and data['dir']==('rtl' if locale=='ar' else 'ltr'),(path,data)
    assert data['theme']==theme and data['heading'] and not data['overflow'] and data['lastActionTappable'] and data['authenticated'],(path,data)
print('24 connected real-browser observations verified at 1440 and 390 pixels; verify screenshot files separately.')
PY
