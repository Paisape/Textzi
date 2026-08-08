#!/usr/bin/env bash
set -euo pipefail

if ! pg_isready -q 2>/dev/null; then
  sudo -u postgres pg_ctlcluster "$(ls /etc/postgresql | head -1)" main start
fi

if ! redis-cli ping >/dev/null 2>&1; then
  redis-server --daemonize yes --port 6379
fi

for _ in $(seq 1 30); do
  pg_isready -q && redis-cli ping >/dev/null 2>&1 && exit 0
  sleep 1
done

echo "Timed out waiting for PostgreSQL or Redis" >&2
exit 1
