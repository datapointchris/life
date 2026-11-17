#!/usr/bin/env bash
# Brings production's owner and app roles to life/database/roles.sql, as the
# server's superuser on the Postgres container's own socket, where no password
# is asked.
#
# It reads POSTGRES_OWNER_PASSWORD, POSTGRES_SUPERUSER_PASSWORD and
# POSTGRES_PASSWORD, the app's, from its environment. The deploy runs it under
# `sops exec-env` of both secrets files, so no password reaches a file or a
# process's arguments:
#
#   sops exec-env secrets/secrets.prod.enc.env \
#     'sops exec-env secrets/secrets.postgres-roles.prod.enc.env scripts/converge-database-roles.sh'
set -euo pipefail

container="${1:-life-infra-postgres}"
cd "$(dirname "$0")/.."

POSTGRES_APP_PASSWORD="$POSTGRES_PASSWORD" docker exec -i \
  -e POSTGRES_OWNER_PASSWORD -e POSTGRES_APP_PASSWORD -e POSTGRES_SUPERUSER_PASSWORD \
  "$container" psql -U postgres -d "${POSTGRES_DB:-life}" -X -q --single-transaction -f - \
  < <(cat scripts/converge-database-roles.psql life/database/roles.sql)
