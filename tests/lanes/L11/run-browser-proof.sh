#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
: "${TEST_DATABASE_ADMIN_URL:?Pass the local PostgreSQL maintenance URL for disposable proofs}"
export CHROME_DEVTOOLS_AXI_SESSION=bt-l11
case "${L11_WEB_MODE:-production}" in production) next_command=start;; dev) next_command=dev;; *) echo 'Choose production or dev proof mode' >&2; exit 2;; esac
(cd web && node scripts/generate-nav.mjs)
mkdir -p tests/lanes/L11/evidence
for port in 3111 38101 38102 38109; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then echo "Proof port $port is already in use; nothing was stopped" >&2; exit 2; fi
done
PYTHONPATH=tests/lanes .venv/bin/python -m L11.browser_fixture > .venv/browser-fixture.log 2>&1 & fixture=$!
BT_PUBLIC_WEB_ORIGINS=http://127.0.0.1:3111 BT_TRUST_FORWARDED_ORIGIN=false \
IDENTITY_API_URL=http://127.0.0.1:38101 CATALOG_API_URL=http://127.0.0.1:38102 SERVICE_OPERATIONS_API_URL=http://127.0.0.1:38109 \
  node web/node_modules/next/dist/bin/next "$next_command" web --hostname 127.0.0.1 --port 3111 > .venv/web.log 2>&1 & web=$!
cleanup() { chrome-devtools-axi stop >/dev/null 2>&1 || true; kill "$web" "$fixture" 2>/dev/null || true; wait "$web" "$fixture" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
for _ in {1..50}; do
  if curl -fsS http://127.0.0.1:3111/api/health >/dev/null 2>&1 && curl -fsS http://127.0.0.1:38109/health/ready >/dev/null 2>&1; then break; fi
  sleep .2
done
curl -fsS http://127.0.0.1:3111/api/health >/dev/null
curl -fsS http://127.0.0.1:38109/health/ready >/dev/null
curl -fsSL --max-redirs 5 http://127.0.0.1:3111/en/services > .venv/proof-page.html
authority='contract fixture'
if [ "${L11_REAL_ACCOUNTS_PROOF:-0}" = 1 ]; then authority='real Accounts routes; business/staff V1 fixture'; fi
printf '{"mode":"%s","identity":"%s","domain_persistence":"isolated PostgreSQL","web_host":"127.0.0.1"}\n' "${L11_WEB_MODE:-production}" "$authority" > tests/lanes/L11/evidence/environment.json
echo 'Proof services ready'
chrome-devtools-axi open http://127.0.0.1:3111/en/services >/dev/null
check_json() { .venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); assert isinstance(d,dict) and d and all(v is True for v in d.values())' "$1"; }
for variant in 'desktop|1440x1000x1' 'phone|390x844x1,mobile,touch' 'narrow|320x740x1,mobile,touch' 'landscape|932x430x1,mobile,touch'; do
  name=${variant%%|*}; viewport=${variant#*|}
  chrome-devtools-axi emulate --viewport "$viewport" >/dev/null
  chrome-devtools-axi run < tests/lanes/L11/browser-matrix.js > "tests/lanes/L11/evidence/$name-dom.json"
  .venv/bin/python -m json.tool "tests/lanes/L11/evidence/$name-dom.json" >/dev/null
  echo "$name matrix passed"
done
chrome-devtools-axi run < tests/lanes/L11/gateway-proof.js > tests/lanes/L11/evidence/gateway-dom.json
check_json tests/lanes/L11/evidence/gateway-dom.json
status=$(curl -s -o .venv/csrf-denied.json -w '%{http_code}' -X POST -H 'Origin: https://foreign.invalid' -H 'Authorization: Bearer buyer' -H 'Content-Type: application/json' -H 'Idempotency-Key: refused-csrf-proof' -d '{}' http://127.0.0.1:3111/api/web/v1/service-operations/v1/directory/choices)
[ "$status" = 403 ]
.venv/bin/python -c 'import json; assert json.load(open(".venv/csrf-denied.json"))["error"]["code"]=="invalid_origin"'
echo 'Gateway persistence/privacy/replay and foreign-origin refusal passed'
chrome-devtools-axi open 'http://127.0.0.1:3111/en/services?business=00000000-0011-4000-8000-000000000001' >/dev/null
curl -fsS -X POST 'http://127.0.0.1:38109/proof/dependency?unavailable=true' >/dev/null
chrome-devtools-axi run > .venv/outage-1.json <<'JS'
await page.click('.directory-list-heading button');await page.wait(500);
const valid=await page.eval(()=>document.querySelectorAll('.directory-business').length===0&&document.querySelector('main').textContent.includes('The directory cannot verify businesses'));
if(!valid)throw new Error('Directory outage retained unverified businesses');
console.log(JSON.stringify({directory_hides_unverified:true}));
JS
check_json .venv/outage-1.json
curl -fsS -X POST 'http://127.0.0.1:38109/proof/dependency?unavailable=false' >/dev/null
chrome-devtools-axi wait 11000 >/dev/null
chrome-devtools-axi run > .venv/outage-2.json <<'JS'
await page.click('.directory-page > .card button');await page.wait('.directory-business');
console.log(JSON.stringify({directory_recovers:true}));
JS
check_json .venv/outage-2.json
curl -fsS -X POST 'http://127.0.0.1:38102/proof/dependency?unavailable=true' >/dev/null
chrome-devtools-axi run > .venv/outage-3.json <<'JS'
await page.open('http://127.0.0.1:3111/en/services?business=00000000-0011-4000-8000-000000000001');
await page.wait('.movement-panel > div[role="alert"]');
const valid=await page.eval(()=>document.querySelectorAll('.directory-business').length===1&&!document.querySelector('.movement-facts')&&document.querySelector('.movement-panel').textContent.includes('Movement options are temporarily unavailable'));
if(!valid)throw new Error('Movement outage fabricated compatibility, price or whole-directory failure');
console.log(JSON.stringify({movement_failure_isolated:true,no_invented_price:true}));
JS
check_json .venv/outage-3.json
curl -fsS -X POST 'http://127.0.0.1:38102/proof/dependency?unavailable=false' >/dev/null
chrome-devtools-axi wait 11000 >/dev/null
chrome-devtools-axi run > .venv/outage-4.json <<'JS'
await page.click('.movement-panel > div[role="alert"] button');await page.wait('.movement-panel input');
console.log(JSON.stringify({movement_recovers:true}));
JS
check_json .venv/outage-4.json
printf '{"directory_hides_unverified":true,"directory_recovers":true,"movement_failure_isolated":true,"no_invented_price":true,"movement_recovers":true}\n' > tests/lanes/L11/evidence/outage-dom.json
if [ "${L11_REAL_ACCOUNTS_PROOF:-0}" = 1 ]; then
  for variant in 'desktop|1440x1000x1' 'phone|390x844x1,mobile,touch'; do
    name=${variant%%|*}; viewport=${variant#*|}
    chrome-devtools-axi emulate --viewport "$viewport" >/dev/null
    chrome-devtools-axi run < tests/lanes/L11/buyer-ui-proof.js > "tests/lanes/L11/evidence/buyer-$name-dom.json"
    .venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); assert len(d["cases"])==4 and d["cross_buyer_isolation"] is True and d["revoked_session_clears_private_state"] is True' "tests/lanes/L11/evidence/buyer-$name-dom.json"
    echo "$name real-buyer UI persistence/privacy/units passed"
  done
fi
node tests/lanes/L11/capture.cjs
