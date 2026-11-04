#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
tree=$(printf '%s' "$PWD" | shasum -a 256 | cut -c1-8)
run="$tree-$$"
# Reuse installed dependencies, but mount current code/tests/contracts read-only.
image=${L10_TEST_IMAGE:-$(docker image ls --filter "reference=beirut-time/l10-options:test-$tree-*" --format '{{.Repository}}:{{.Tag}}' | awk 'NR==1{print;exit}')}
if [ -z "$image" ] || [ "${L10_REBUILD_IMAGE:-0}" = 1 ]; then
  base="beirut-time/l10-foundation:test-$run"
  image="beirut-time/l10-options:test-$run"
  docker build --target test -f services/_template/runtime/Dockerfile -t "$base" .
  docker build --target test -f tests/lanes/L10/Dockerfile --build-arg "FOUNDATION_IMAGE=$base" -t "$image" .
fi
config=$(./infra/foundation/compose.sh config --format json)
network=$(printf '%s' "$config" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"]+"_default")')
password=$(printf '%s' "$config" | python3 -c 'import json,sys; from urllib.parse import quote; print(quote(json.load(sys.stdin)["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"],safe=""))')
runtime=$(printf '%s' "$config" | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["catalog"]["environment"]["BT_DATABASE_URL"])')
./infra/foundation/compose.sh up -d --wait --no-recreate postgres
test_container="bt-l10-tests-$run"
lint_container="bt-l10-lint-$run"
# Leave stopped proof containers intact; never prune shared storage or image layers.
trap 'docker stop "$test_container" "$lint_container" >/dev/null 2>&1 || true' EXIT
mounts=(-v "$PWD/packages:/proof/packages:ro"
  -v "$PWD/tests/lanes/L10:/lane-tests/L10:ro"
  -v "$PWD/services/_template/runtime:/proof/template:ro"
  -v "$PWD/services/_template/runtime/tests:/app/tests:ro"
  -v "$PWD/services/_template/runtime/service_app:/app/service_app:ro"
  -v "$PWD/tests/foundation:/foundation-tests:ro"
  -v "$PWD/contracts:/contracts:ro"
  -v "$PWD/packages/contracts-catalog/options:/opt/domain-contracts/bt_contracts/catalog/options:ro")
for kind in color material dial sophistication; do
  mounts+=(-v "$PWD/services/catalog/modules/options/$kind:/app/modules/options/$kind:ro")
done
python_path=/proof/packages/runtime/src:/proof/packages/events/src:/proof/packages/bulkheads/src:/proof/packages/contracts-core/src:/opt/domain-contracts
echo "Reusing $image with current source mounts"
docker run --name "$test_container" --memory 256m --cpus .5 --pids-limit 128 --read-only --tmpfs /tmp \
  --network "$network" "${mounts[@]}" -e "PYTHONPATH=$python_path" \
  -e "TEST_DATABASE_ADMIN_URL=postgresql://postgres:$password@postgres:5432/postgres" \
  -e "TEST_RUNTIME_URL=$runtime" -e BT_SERVICE_NAME=catalog -e BT_TEST_LANE=L10 \
  -e BT_MODULES_PATH=/tmp/l10-core-baseline "$image" sh -c \
  'python /lane-tests/L10/check_dependencies.py && python /proof/template/run_tests.py'
docker run --name "$lint_container" -v "$PWD:/work:ro" "$image" ruff check --no-cache \
  /work/services/catalog/modules/options/color /work/services/catalog/modules/options/material \
  /work/services/catalog/modules/options/dial /work/services/catalog/modules/options/sophistication \
  /work/packages/contracts-catalog/options /work/tests/lanes/L10
pnpm --filter beirut-time-web lint
pnpm --filter beirut-time-web typecheck
pnpm build
pnpm test
pnpm --filter beirut-time-web exec vitest run --config features/brand-options/vitest.config.ts
python3 infra/foundation/discover-contracts.py
./infra/foundation/compose.sh config --quiet
