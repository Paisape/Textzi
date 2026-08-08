#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_BIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)"
if [[ -n "$PG_BIN" ]]; then
  export PATH="$PG_BIN:$PATH"
fi
PGDATA="$ROOT/.local/postgres/data"
PGSOCKET="$ROOT/.local/postgres/run"
REDIS_DIR="$ROOT/.local/redis"

mkdir -p "$PGDATA" "$PGSOCKET" "$REDIS_DIR"

if [[ ! -f "$PGDATA/PG_VERSION" ]]; then
  initdb -D "$PGDATA" --auth=trust --encoding=UTF8
fi

if ! pg_isready -h localhost -p 5432 -q 2>/dev/null; then
  pg_ctl -D "$PGDATA" -l "$PGDATA/logfile" start \
    -o "-c unix_socket_directories=$PGSOCKET -c listen_addresses=localhost -p 5432"
fi

if ! redis-cli ping >/dev/null 2>&1; then
  redis-server --daemonize yes --port 6379 --dir "$REDIS_DIR" --pidfile "$REDIS_DIR/redis.pid"
fi

for _ in $(seq 1 30); do
  pg_isready -h localhost -p 5432 -q && redis-cli ping >/dev/null 2>&1 && exit 0
  sleep 1
done

echo "Timed out waiting for PostgreSQL or Redis" >&2
exit 1
