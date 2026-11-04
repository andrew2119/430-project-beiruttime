#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
: "${TEST_DATABASE_ADMIN_URL:?Supply the isolated-test PostgreSQL maintenance URL}"
export CHROME_DEVTOOLS_AXI_SESSION=bt-l02
proof=tests/lanes/L02/.contract-runtime
mkdir -p "$proof" tests/lanes/L02/evidence
rm -f "$proof/browser.json" "$proof/stop-browser"
BT_L02_BROWSER_DEMO=1 BT_L02_BROWSER_SECONDS=300 \
BT_ALLOWED_WEB_ORIGINS=http://localhost:3202,http://127.0.0.1:3202,http://identity \
.venv/bin/python -m pytest tests/lanes/L02/test_browser_live.py -s -q -p no:cacheprovider > "$proof/browser-service.log" 2>&1 &
service=$!
web=''
cleanup() {
  if [ -n "$web" ]; then kill "$web" 2>/dev/null || true; wait "$web" || true; fi
  touch "$proof/stop-browser"
  wait "$service" || true
}
trap cleanup EXIT
for attempt in {1..100}; do
  [ ! -f "$proof/browser.json" ] || break
  kill -0 "$service" 2>/dev/null || { printf '%s\n' 'Live Identity proof did not start'; exit 1; }
  sleep .1
done
[ -f "$proof/browser.json" ] || { printf '%s\n' 'Timed out waiting for the live Identity proof'; exit 1; }
IDENTITY_API_URL=http://127.0.0.1:8202 BT_PUBLIC_WEB_ORIGINS=http://localhost:3202,http://127.0.0.1:3202 BT_TRUST_FORWARDED_ORIGIN=false node web/node_modules/next/dist/bin/next start web -p 3202 > "$proof/browser-web.log" 2>&1 &
web=$!
for attempt in {1..50}; do
  if curl --max-time 1 -fsS http://localhost:3202/api/health >/dev/null 2>&1; then break; fi
  kill -0 "$web" 2>/dev/null || { printf '%s\n' 'Production web proof did not start'; exit 1; }
  sleep .1
done
node tests/lanes/L02/headless-browser-proof.mjs
