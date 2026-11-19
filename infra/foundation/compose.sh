#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
# Discover lane-owned files without creating or editing any of them.
for lane in 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25; do
  variable="BT_COMPOSE_L${lane}"
  file="infra/compose/L${lane}.yaml"
  if [ -f "$file" ]; then export "$variable=$file"; else unset "$variable"; fi
done
exec docker compose "$@"
