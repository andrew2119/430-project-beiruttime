#!/usr/bin/env bash
set -euo pipefail
# Each service owns one database; runtime roles cannot connect to sibling databases
# or perform DDL. Migration owners are never injected into application containers.
for service in identity catalog auction pricing orders eligibility trust communications service_ops; do
  key="$(printf '%s' "$service" | tr '[:lower:]' '[:upper:]')"
  runtime_key="${key}_DB_PASSWORD"; owner_key="${key}_OWNER_PASSWORD"
  runtime="bt_${service}"; owner="${runtime}_owner"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v runtime="$runtime" -v owner="$owner" -v db="$runtime" \
    -v runtime_password="${!runtime_key}" -v owner_password="${!owner_key}" <<'SQL'
CREATE ROLE :"owner" LOGIN PASSWORD :'owner_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE :"runtime" LOGIN PASSWORD :'runtime_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE :"db" OWNER :"owner";
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO :"runtime";
SQL
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$runtime" \
    -v runtime="$runtime" -v owner="$owner" <<'SQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO :"owner";
GRANT USAGE ON SCHEMA public TO :"runtime";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO :"runtime";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT USAGE,SELECT ON SEQUENCES TO :"runtime";
SQL
done
# No application role may use the maintenance database as an isolation escape hatch.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
SQL
