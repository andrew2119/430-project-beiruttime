#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export CHROME_DEVTOOLS_AXI_SESSION="${CHROME_DEVTOOLS_AXI_SESSION:-bt-foundation}"
mkdir -p artifacts
chrome-devtools-axi emulate --viewport '1440x900x1' >/dev/null
chrome-devtools-axi run < tests/foundation/browser-matrix.js > artifacts/browser-desktop.json
chrome-devtools-axi emulate --viewport '390x844x3,mobile,touch' >/dev/null
chrome-devtools-axi run < tests/foundation/browser-matrix.js > artifacts/browser-phone.json
printf 'Production browser matrix passed; evidence in artifacts/browser-{desktop,phone}.json\n'
