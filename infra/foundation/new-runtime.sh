#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
service="${1:?Usage: new-runtime.sh service}"
case "$service" in identity|eligibility|catalog|auction|pricing|communications|orders|trust|service-operations) ;; *) echo 'Unknown service' >&2; exit 2;; esac
if [ -e "services/$service/runtime" ]; then echo 'Runtime already exists; refusing overwrite' >&2; exit 2; fi
mkdir -p "services/$service/modules"
cp -R services/_template/runtime "services/$service/runtime"
printf 'Created services/%s/runtime. Set SERVICE_PATH=services/%s in your lane compose build args.\n' "$service" "$service"
