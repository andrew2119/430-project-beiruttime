#!/bin/bash
set -euo pipefail
export CHROME_DEVTOOLS_AXI_SESSION="${CHROME_DEVTOOLS_AXI_SESSION:-bt-l03}"
BASE="${BASE_URL:-http://localhost:3103}"
chrome-devtools-axi open "$BASE/en/image-credits" >/dev/null
for width in 1440 390; do
  viewport=1440x900x1; [ "$width" != 390 ] || viewport=390x844x3,mobile,touch
  chrome-devtools-axi emulate --viewport "$viewport" >/dev/null
  for locale in en ar; do
    for theme in light dark; do
      chrome-devtools-axi eval "() => {document.cookie='bt-theme=$theme; Path=/; SameSite=Lax';return true;}" >/dev/null
      for route in image-credits seller/listings seller/dashboard; do
        chrome-devtools-axi eval "() => {location.href='$BASE/$locale/$route';return 'navigating';}" >/dev/null
        chrome-devtools-axi wait 350 >/dev/null
        printf '%s %s %s %s: ' "$width" "$locale" "$theme" "$route"
        chrome-devtools-axi eval "async () => {
          const root=document.documentElement;
          if(innerWidth!==$width)throw new Error('wrong emulated viewport width: '+innerWidth);
          if(root.dir!=='$([ "$locale" = ar ] && echo rtl || echo ltr)'||root.dataset.theme!=='$theme')throw new Error('preference mismatch');
          if(!document.querySelector('main h1')?.textContent)throw new Error('missing heading');
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
