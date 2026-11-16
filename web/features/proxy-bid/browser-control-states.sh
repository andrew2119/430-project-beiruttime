#!/usr/bin/env bash
# Shared controls are checked in the controls gallery and the real buyer tab.
set -euo pipefail
: "${BT_BUYER_SHOTS:?Set screenshot/evidence directory}"
export CHROME_DEVTOOLS_AXI_SESSION=bt-buyer
for app in reference buyer; do
  port=33515; path=buyer-reference; label=Refresh
  if [ "$app" = buyer ]; then port=33517; path=en/buyer; label='Try again'; fi
  for theme in light dark; do
    chrome-devtools-axi eval "() => {document.cookie='bt-theme=$theme; Path=/';}" >/dev/null
    chrome-devtools-axi open "http://127.0.0.1:$port/$path" >/dev/null
    chrome-devtools-axi wait 600 >/dev/null
    tree=$(chrome-devtools-axi snapshot)
    uid=$(LABEL="$label" TREE="$tree" python3 - <<'PY'
import os,re
m=re.search(r'uid=(\S+) button "'+re.escape(os.environ['LABEL'])+r'"',os.environ['TREE'])
if not m:raise SystemExit('Header action missing')
print(m[1])
PY
)
    chrome-devtools-axi hover "@$uid" >/dev/null
    chrome-devtools-axi run <<'JS' > "$BT_BUYER_SHOTS/control-$app-$theme.json"
const selector='main .hx-actions button';
const initialTheme=await page.eval(()=>document.documentElement.dataset.theme);
const hover=await page.eval(()=>{const b=document.querySelector('main .hx-actions button'),s=getComputedStyle(b),canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');ctx.fillStyle=s.color;ctx.fillRect(0,0,1,1);return{hovered:b.matches(':hover'),height:b.getBoundingClientRect().height,transition:s.transition,shadow:s.boxShadow,color:[...ctx.getImageData(0,0,1,1).data],background:s.backgroundColor};});
await page.eval(()=>document.querySelector('main .hx-actions button').focus());await page.press('Tab');await page.press('Shift+Tab');
const focused=await page.eval(()=>document.querySelector('main .hx-actions button').matches(':focus-visible'));
await page.eval(()=>{window.__buyerPress=null;const b=document.querySelector('main .hx-actions button');b.addEventListener('keyup',()=>{window.__buyerPress={active:b.matches(':active'),transition:getComputedStyle(b.querySelector('span')).transition,transform:getComputedStyle(b.querySelector('span')).transform};},{once:true});});
await page.press('Space');
const press=await page.eval(()=>window.__buyerPress);
console.log(JSON.stringify({initialTheme,hover,focused,press},null,2));
JS
  done
done
