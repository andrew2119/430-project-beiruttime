#!/usr/bin/env bash
# Requires a current production build. Native actions only; artifact capture via CDP.
set -euo pipefail
cd "$(dirname "$0")/../../.."
: "${BT_L14_BROWSER_CONTEXT:?Supply current synthetic native login context}"
export CHROME_DEVTOOLS_AXI_SESSION=bt-s2-l14-q02
export CHROME_DEVTOOLS_AXI_BROWSER_URL=http://127.0.0.1:19615
export BT_L14_CAPTURE_PORT=19615
base=http://127.0.0.1:3640
mkdir -p tests/lanes/L14/.local/offers-browser
python3 - <<'PY'
import socket
with socket.socket() as s:s.bind(('127.0.0.1',19615))
PY
profile=$(mktemp -d "$PWD/tests/lanes/L14/.local/chrome-q02.XXXXXX")
chrome_pid=''
cleanup(){
  chrome-devtools-axi stop >/dev/null 2>&1 || true
  if [ -n "$chrome_pid" ]; then kill "$chrome_pid" 2>/dev/null || true; wait "$chrome_pid" 2>/dev/null || true; fi
  rm -rf -- "$profile"
}
trap cleanup EXIT
'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' --headless=new --disable-gpu --hide-scrollbars --no-first-run --remote-debugging-address=127.0.0.1 --remote-debugging-port=19615 --user-data-dir="$profile" about:blank > tests/lanes/L14/.local/q02-chrome.log 2>&1 &
chrome_pid=$!
python3 - <<'PY'
import time,urllib.request
for _ in range(100):
    try:urllib.request.urlopen('http://127.0.0.1:19615/json/version',timeout=1).close();break
    except OSError:time.sleep(.1)
else:raise RuntimeError('Owned Q02 headless Chrome did not start')
PY
chrome-devtools-axi open "$base/en/account" >/dev/null
chrome-devtools-axi emulate --viewport '1280x900x1' >/dev/null
python3 - <<'PY' | chrome-devtools-axi run > tests/lanes/L14/.local/q02-connected/browser-compose.json
import os,pathlib
print('const context='+os.environ['BT_L14_BROWSER_CONTEXT']+';')
print(pathlib.Path('tests/lanes/L14/offers-login.mjs').read_text())
print(pathlib.Path('tests/lanes/L14/offers-compose.mjs').read_text())
PY
observe(){
 local phase=$1 proof_file=$2 listing
 listing=$(python3 -c 'import sys,json;print(json.load(open(sys.argv[1]))["listing_id"])' "$proof_file")
 for width in 1280 390; do
  if [ "$width" = 390 ]; then chrome-devtools-axi emulate --viewport '390x844x3,mobile,touch' >/dev/null; else chrome-devtools-axi emulate --viewport '1280x900x1' >/dev/null; fi
  for locale in en ar; do
   for theme in light dark; do
    chrome-devtools-axi eval "()=>{document.cookie='bt-theme=$theme; Path=/; SameSite=Lax';return true;}" >/dev/null
    url="$base/$locale/offers?listing=$listing"
    chrome-devtools-axi open "$url" >/dev/null
    python3 - "$proof_file" <<'PY' | chrome-devtools-axi run > "tests/lanes/L14/.local/offers-browser/${phase}-${width}-${locale}-${theme}.json"
import pathlib,sys
print('const proof='+pathlib.Path(sys.argv[1]).read_text()+';')
print(pathlib.Path('tests/lanes/L14/offers-observe.mjs').read_text())
PY
    node tests/lanes/L14/capture-shot.mjs "$PWD/tests/lanes/L14/.local/offers-browser/${phase}-${width}-${locale}-${theme}.png" "$url"
   done
  done
 done
}
observe compose tests/lanes/L14/.local/q02-connected/browser-compose.json
# The actual preview/send/accept/review controls run at the final real 390px
# viewport; desktop and both localized form/state projections are checked too.
python3 - <<'PY' | chrome-devtools-axi run > tests/lanes/L14/.local/q02-connected/browser-actions.json
import os,pathlib
print('const context='+os.environ['BT_L14_BROWSER_CONTEXT']+';')
print(pathlib.Path('tests/lanes/L14/offers-login.mjs').read_text())
print(pathlib.Path('tests/lanes/L14/offers-actions.mjs').read_text())
PY
observe accepted tests/lanes/L14/.local/q02-connected/browser-actions.json
python3 - <<'PY'
import json,pathlib
root=pathlib.Path('tests/lanes/L14/.local/offers-browser')
proof=json.loads(pathlib.Path('tests/lanes/L14/.local/q02-connected/browser-actions.json').read_text())
copy={locale:json.loads(pathlib.Path(f'web/features/pricing/s2-{locale}.json').read_text()) for locale in ['en','ar']}
observations=list(root.glob('compose-*.json'))+list(root.glob('accepted-*.json'));assert len(observations)==16
for path in observations:
    data=json.loads(path.read_text());phase,width,locale,theme=path.stem.rsplit('-',3)
    assert data['viewport']==int(width) and data['locale']==locale and data['theme']==theme,(path,data)
    assert data['dir']==('rtl' if locale=='ar' else'ltr') and not data['overflow'] and data['composable']==(phase=='compose'),(path,data)
    if phase=='compose':assert copy[locale]['sampleListing'] in data['compose_text'],(path,data)
    else:
        accepted=next(row for row in data['offers'] if row['id']==proof['offer_id'])
        assert copy[locale]['accepted'] in accepted['text'],(path,data)
    assert path.with_suffix('.png').stat().st_size>1000
print('Native buyer create/seller accept/scoped order review at 390px and 16 form/accepted EN/AR/theme/desktop/phone observations/screenshots passed; no payment invoked.')
PY
