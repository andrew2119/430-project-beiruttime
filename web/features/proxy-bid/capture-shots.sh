#!/usr/bin/env bash
# Isolated headless Chrome screenshots; chrome-devtools-axi is used separately
# for the complete DOM/interaction matrix. See capture-shots.mjs for the Mac
# CLI's cropped-390px/pre-hydration workaround.
set -euo pipefail
exec node "$(dirname "$0")/capture-shots.mjs"
