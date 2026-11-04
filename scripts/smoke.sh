#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
compose() { ./infra/foundation/compose.sh "$@"; }
# Cleanup stops only services that were not running when this invocation began.
services="identity catalog auction pricing orders eligibility trust communications service-operations"
started="$(compose ps --services --status running)"
cleanup() {
  if [ "${KEEP_RUNNING:-0}" != 1 ]; then
    for name in web $services; do
      if ! printf '%s\n' "$started" | grep -qx "$name"; then compose stop "$name" >/dev/null; fi
    done
  fi
}
trap cleanup EXIT
./infra/foundation/dev.sh
port=8101
for service in $services; do
  for endpoint in live ready; do
    curl --fail --silent --show-error "http://127.0.0.1:$port/health/$endpoint" > /dev/null
  done
  port=$((port+1))
done
curl --fail --silent --show-error http://127.0.0.1:3000/api/health > /dev/null
for locale in en ar; do
  for theme in light dark; do
    curl --fail --silent --show-error -H "Cookie: bt-theme=$theme" "http://127.0.0.1:3000/$locale" | \
      python3 -c 'import sys; s=sys.stdin.read(); assert "Beirut Time" in s and "main-content" in s; assert "data-theme=\"'"$theme"'\"" in s; assert "lang=\"'"$locale"'\"" in s'
  done
done
curl --fail --silent http://127.0.0.1:3000/api/web/v1/status | python3 -c 'import json,sys; data=json.load(sys.stdin); assert len(data["services"])==9; assert all(s["status"]=="ready" for s in data["services"]), data'
echo 'All nine services, web, bilingual themes and BFF health checks passed.'
