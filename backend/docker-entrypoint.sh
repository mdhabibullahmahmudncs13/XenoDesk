#!/bin/sh
# Runs migrations only for the service that owns them (the API), then hands the
# process over to the container command. Worker instances skip this and wait for
# the API healthcheck instead, so two containers never migrate concurrently.
set -e

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    echo "running migrations as the schema owner"
    alembic upgrade head
fi

exec "$@"
