#!/usr/bin/env bash
# Runs once, on first start of an empty data directory (docker-entrypoint-initdb.d).
# Per service: <svc>_owner owns the schema and runs migrations; <svc>_app gets DML only, so the
# running service cannot alter its own schema (DESIGN.md section 5).
set -euo pipefail

: "${PRODUCT_OWNER_PASSWORD:?}" "${PRODUCT_APP_PASSWORD:?}"
: "${ORDER_OWNER_PASSWORD:?}" "${ORDER_APP_PASSWORD:?}"

psql_admin() { psql -v ON_ERROR_STOP=1 --username postgres "$@"; }

create_service_db() {  # $1 = service prefix, $2 = owner password, $3 = app password
  local svc=$1
  # Passwords go in as psql variables (:'name') so quoting is always correct.
  psql_admin --dbname postgres -v owner_pw="$2" -v app_pw="$3" <<SQL
CREATE ROLE ${svc}_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE ${svc}_app   LOGIN PASSWORD :'app_pw';
CREATE DATABASE ${svc}_db OWNER ${svc}_owner;
REVOKE ALL ON DATABASE ${svc}_db FROM PUBLIC;
GRANT CONNECT ON DATABASE ${svc}_db TO ${svc}_app;
-- A stuck transaction holding a lock is the failure we want killed, not waited on (section 8).
ALTER ROLE ${svc}_app SET statement_timeout = '5s';
ALTER ROLE ${svc}_app SET idle_in_transaction_session_timeout = '30s';
SQL
  psql_admin --dbname "${svc}_db" <<SQL
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO ${svc}_app;
-- Tables the owner creates later (Alembic) are automatically usable by the app role.
ALTER DEFAULT PRIVILEGES FOR ROLE ${svc}_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${svc}_app;
SQL
}

create_service_db product "$PRODUCT_OWNER_PASSWORD" "$PRODUCT_APP_PASSWORD"
create_service_db order   "$ORDER_OWNER_PASSWORD"   "$ORDER_APP_PASSWORD"
