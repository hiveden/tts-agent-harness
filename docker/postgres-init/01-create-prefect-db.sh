#!/bin/bash
#
# Create a dedicated `prefect` database on first boot.
#
# Rationale (ADR-001 §2.1 / §3.1):
#   Business schema and Prefect metadata share the same Postgres instance
#   but live in separate databases to avoid accidental coupling.
#
# Idempotent: skipped entirely on subsequent boots because
# /docker-entrypoint-initdb.d only runs when the data dir is empty.
#

set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE prefect'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'prefect')\gexec
EOSQL

echo "ensured database: prefect"
