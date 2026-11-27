#!/usr/bin/env bash
# Create every service's runtime and owner roles and database on the job's own PostgreSQL.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PGHOST=127.0.0.1 PGPORT=54329 PGUSER=postgres PGDATABASE=postgres POSTGRES_USER=postgres
export PGPASSWORD=local-bootstrap-only
for _ in $(seq 1 60); do
  pg_isready -q && break
  sleep 1
done
pg_isready
for service in identity catalog auction pricing orders eligibility trust communications service_ops; do
  key="$(printf '%s' "$service" | tr '[:lower:]' '[:upper:]')"
  password="local-${service//_/-}"
  export "${key}_DB_PASSWORD=$password" "${key}_OWNER_PASSWORD=$password-owner"
done
bash "$root/infra/foundation/postgres-init.sh"
