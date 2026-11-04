#!/usr/bin/env bash
set -euo pipefail
# Real-browser route/geometry checks. Sign in through Identity before running an
# authorized scenario; this script never injects tokens or grants permissions.
cd "$(dirname "$0")/../../.."
export CHROME_DEVTOOLS_AXI_SESSION="${CHROME_DEVTOOLS_AXI_SESSION:-bt-l09}"
BASE="${BT_BROWSER_BASE:-http://localhost:3000}"
ROUTES="${BT_BROWSER_ROUTES:-operations/moderation operations/dashboard business-intake}"
set -f
mkdir -p artifacts/l09/browser
trap 'chrome-devtools-axi stop >/dev/null 2>&1 || true' EXIT
chrome-devtools-axi open "$BASE/en/operations/moderation" >/dev/null
for width in 1440 390; do
  if [ "$width" = 390 ]; then
    chrome-devtools-axi emulate --viewport 390x844x3,mobile,touch >/dev/null
  else
    chrome-devtools-axi emulate --viewport 1440x900x1 >/dev/null
  fi
  for locale in en ar; do
    for theme in light dark; do
      for route in $ROUTES; do
        chrome-devtools-axi open "$BASE/$locale/$route" >/dev/null
        chrome-devtools-axi eval "() => { if(document.documentElement.dataset.theme!=='$theme')document.querySelector('.preferences .icon-button').click(); return true; }" >/dev/null
        chrome-devtools-axi wait 1200 >/dev/null
        result=$(chrome-devtools-axi eval "() => { if(innerWidth!==$width)throw Error('Wrong effective viewport width');if(!document.querySelector('.ops-header h1'))throw Error('Missing operations heading');if(document.documentElement.scrollWidth>innerWidth)throw Error('Horizontal page overflow');if(document.documentElement.dir!==('$locale'==='ar'?'rtl':'ltr'))throw Error('Wrong locale direction');const rgb=getComputedStyle(document.body).backgroundColor.match(/\\d+/g)?.slice(0,3).map(Number)??[];const brightness=rgb.reduce((a,b)=>a+b,0)/3;if(rgb.length!==3||('$theme'==='dark'?brightness>100:brightness<180))throw Error('Theme paint mismatch');const clipped=[...document.querySelectorAll('.ops-page *, .masthead *')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&(r.left<-.5||r.right>innerWidth+.5)});if(clipped.length)throw Error('Clipped operations/header element');if($width===390){for(const element of document.querySelectorAll('.ops-page button,.ops-page a,.ops-form input,.ops-form select,.ops-form textarea')){const target=element.matches('input[type=checkbox]')?element.closest('label'):element;const r=target.getBoundingClientRect();if(r.width>0&&(r.width<43.5||r.height<43.5))throw Error('Phone touch target too small');if(element.matches('input:not([type=checkbox]),select,textarea')&&parseFloat(getComputedStyle(element).fontSize)<16)throw Error('Phone field font below floor');}}return JSON.stringify({heading:document.querySelector('.ops-header h1')?.textContent,dir:document.documentElement.dir,theme:document.documentElement.dataset.theme,overflow:document.documentElement.scrollWidth>innerWidth,forms:[...document.querySelectorAll('.ops-form input,.ops-form textarea')].length,privateStorage:Object.keys(localStorage).filter(key=>/token|evidence|serial/i.test(key))}); }")
        printf '%s %s %s %s %s\n' "$width" "$locale" "$theme" "$route" "$result" >> artifacts/l09/browser/matrix.log
        chrome-devtools-axi screenshot "$PWD/artifacts/l09/browser/${width}-${locale}-${theme}-${route//\//-}.png" >/dev/null
      done
    done
  done
done
