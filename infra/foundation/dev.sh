#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
compose() { ./infra/foundation/compose.sh "$@"; }
# Preserve the one shared PostgreSQL process, even across different lane checkouts.
if [ "$#" = 0 ]; then
  set -- identity catalog auction pricing orders eligibility trust communications service-operations web
fi
for service in "$@"; do
  case "$service" in identity|catalog|auction|pricing|orders|eligibility|trust|communications|service-operations|web) ;; *) echo 'Pass domain service names or web' >&2; exit 2;; esac
done
if ! compose ps --services --status running | grep -qx postgres; then
  compose up -d --wait --no-recreate postgres
fi
ready=0
for _ in $(seq 1 60); do
  if compose exec -T postgres pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" = 1 ] || { echo 'Shared PostgreSQL is not ready; no runtime was changed' >&2; exit 1; }
if [ "${SKIP_BUILD:-0}" != 1 ]; then compose build "$@"; fi
for service in "$@"; do
  if [ "$service" != web ]; then compose run --rm --no-deps "$service-migrate"; fi
done
# Migrations ran explicitly above. Do not let a changed bind path recreate shared storage.
exec ./infra/foundation/compose.sh up -d --no-deps --wait --wait-timeout 180 "$@"
