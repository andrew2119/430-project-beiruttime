#!/usr/bin/env bash
# Web lint, type check and the money formatting lane test, each run even if an earlier one fails.
# Usage: .github/ci/web-checks.sh <report.json>
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
report="$1"
passed=()
failed=()
run() {
  local name="$1"
  shift
  echo "::group::$name"
  if "$@"; then passed+=("$name"); else failed+=("$name"); echo "::error::failed: $name"; fi
  echo "::endgroup::"
}
cd "$root" || exit 1
run lint pnpm --filter beirut-time-web lint
run types pnpm --filter beirut-time-web typecheck
run 'money format' node --test tests/lanes/L11/format-money.test.mjs
python3 - "$report" "${#failed[@]}" "${passed[@]}" "--" "${failed[@]}" <<'PY'
import json, sys
report, count, rest = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
split = rest.index('--')
passed, failed = rest[:split], rest[split + 1:]
line = json.dumps(dict(suite='web', ok=not failed and count == 0, problems=[f'{n} failed' for n in failed],
                       steps=passed), sort_keys=True, separators=(',', ':'))
open(report, 'w').write(line + '\n')
print(line)
PY
[[ ${#failed[@]} -eq 0 ]]
