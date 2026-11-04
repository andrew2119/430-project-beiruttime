#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export CHROME_DEVTOOLS_AXI_SESSION="${CHROME_DEVTOOLS_AXI_SESSION:-bt-foundation}"
mkdir -p artifacts
id="$(./infra/foundation/compose.sh ps -q communications)"
[ -n "$id" ] || { echo 'Communications fallback is not running' >&2; exit 2; }
[ "$(docker inspect "$id" --format '{{.Config.Image}}')" = beirut-time/foundation-service:local ] || { echo 'Refusing to stop a domain-owned runtime' >&2; exit 2; }
[ "$(docker inspect "$id" --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}')" = "$(pwd -P)" ] || { echo 'Refusing to stop another checkout’s runtime' >&2; exit 2; }
restored=0
restore() { if [ "$restored" = 0 ]; then docker start "$id" >/dev/null; fi; }
trap restore EXIT
docker stop "$id" >/dev/null
code="$(curl --silent --show-error -o artifacts/dependency-error.json -w '%{http_code}' http://localhost:3000/api/web/v1/status/communications)"
[ "$code" = 503 ]
python3 -c 'import json; x=json.load(open("artifacts/dependency-error.json")); assert x["error"]["code"]=="unavailable" and x["error"]["request_id"]'
curl --fail --silent http://localhost:3000/api/web/v1/status > artifacts/outage-services.json
python3 -c 'import json; x=json.load(open("artifacts/outage-services.json"))["services"]; assert len(x)==9; assert [s["service"] for s in x if s["status"]=="unavailable"]==["communications"]'
curl --fail --silent http://localhost:8102/health/ready >/dev/null
chrome-devtools-axi emulate --viewport '320x664x3,mobile,touch' >/dev/null
chrome-devtools-axi run > artifacts/outage-browser.json <<'JS'
await page.open('http://localhost:3000/en'); await page.wait('.service-grid');
const result=await page.eval(()=>({width:innerWidth,heading:document.querySelector('h1').textContent,overflow:document.body.scrollWidth>innerWidth||document.querySelector('main').scrollWidth>document.querySelector('main').clientWidth,unavailable:[...document.querySelectorAll('.service-grid li')].filter(n=>n.querySelector('.unavailable')).map(n=>n.textContent)}));
if(result.overflow||result.unavailable.length!==1||!result.heading) throw new Error(JSON.stringify(result));
console.log(JSON.stringify(result,null,2));
JS
docker start "$id" >/dev/null
restored=1
for _ in $(seq 1 30); do
  if curl --fail --silent http://localhost:3000/api/web/v1/status | python3 -c 'import sys,json; assert all(s["status"]=="ready" for s in json.load(sys.stdin)["services"])' 2>/dev/null; then
    echo 'Dependency outage isolated to communications; shell, catalog and recovery passed.'
    exit 0
  fi
  sleep 1
done
echo 'Dependency did not recover within the bounded check' >&2
exit 1
