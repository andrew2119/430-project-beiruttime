#!/bin/bash
set -euo pipefail
export CHROME_DEVTOOLS_AXI_SESSION="${CHROME_DEVTOOLS_AXI_SESSION:-bt-l03}"
BASE="${BASE_URL:-http://localhost:3103}"
ROUTES="image-credits seller/listings seller/dashboard"
if [ -n "${LISTING_ID:-}" ]; then
  [[ "$LISTING_ID" =~ ^[0-9a-fA-F-]{36}$ ]] || { echo 'Expected a listing UUID' >&2; exit 1; }
  ROUTES="$ROUTES seller/listings/$LISTING_ID"
fi
# Evaluation failures can be returned as result text with process exit 0.
# Treat them as failures, rather than mistaking permission/outage UI for a pass.
browser_eval() {
  local result
  result=$(chrome-devtools-axi eval "$@")
  printf '%s\n' "$result"
  if printf '%s\n' "$result" | grep -Eq '(^error:|result: "Error:)'; then return 1; fi
}
chrome-devtools-axi open "$BASE/en/image-credits" >/dev/null
for width in 1440 390; do
  viewport=1440x900x1; [ "$width" != 390 ] || viewport=390x844x3,mobile,touch
  chrome-devtools-axi emulate --viewport "$viewport" >/dev/null
  for locale in en ar; do
    for theme in light dark; do
      browser_eval "() => {document.cookie='bt-theme=$theme; Path=/; SameSite=Lax';return true;}" >/dev/null
      for route in $ROUTES; do
        browser_eval "() => {location.href='$BASE/$locale/$route';return 'navigating';}" >/dev/null
        chrome-devtools-axi wait 1000 >/dev/null
        printf '%s %s %s %s: ' "$width" "$locale" "$theme" "$route"
        browser_eval "async () => {
          const root=document.documentElement;
          if(innerWidth!==$width)throw new Error('wrong emulated viewport width: '+innerWidth);
          if(root.dir!=='$([ "$locale" = ar ] && echo rtl || echo ltr)'||root.dataset.theme!=='$theme')throw new Error('preference mismatch');
          if(!document.querySelector('main h1')?.textContent)throw new Error('missing heading');
          if('$route'.startsWith('seller/listings/')&&!document.querySelector('.le-editor-aside img'))throw new Error('owner draft/photo did not load');
          if(root.scrollWidth>innerWidth)throw new Error('horizontal document overflow');
          const images=[...document.querySelectorAll('main img')];images.forEach(image=>{image.loading='eager';});
          await Promise.race([Promise.all(images.map(image=>image.decode())),new Promise((_,reject)=>setTimeout(()=>reject(new Error('image did not decode')),5000))]);
          const links=[...document.querySelectorAll('main a')].filter(a=>a.getClientRects().length);
          if($width<=850&&links.some(a=>a.getBoundingClientRect().height<43))throw new Error('undersized phone link');
          return {heading:document.querySelector('main h1').textContent,dir:root.dir,theme:root.dataset.theme,images:images.length,innerWidth,innerHeight,dpr:devicePixelRatio,overflow:false};
        }"
      done
    done
  done
done
