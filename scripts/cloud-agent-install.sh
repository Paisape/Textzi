#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

"$ROOT/scripts/cloud-agent-start.sh"

if [[ ! -f .env ]]; then
  cp .env.example .env
  sed -i \
    -e 's|@postgres:5432|@localhost:5432|g' \
    -e 's|redis://redis:|redis://localhost:|g' \
    -e 's|@rabbitmq:|@localhost:|g' \
    -e 's|WEB_ORIGIN=.*|WEB_ORIGIN=http://localhost:5173|' \
    -e 's|PUBLIC_API_BASE_URL=.*|PUBLIC_API_BASE_URL=http://localhost:8000|' \
    -e 's|VITE_API_BASE_URL=.*|VITE_API_BASE_URL=http://localhost:8000|' \
    -e 's|JWT_SECRET=.*|JWT_SECRET=development-only-change-me|' \
    -e 's|ADMIN_BOOTSTRAP_KEY=.*|ADMIN_BOOTSTRAP_KEY=development-admin-key-change-me|' \
    -e 's|WORKER_KEY=.*|WORKER_KEY=development-worker-key-change-me|' \
    -e 's|PROVIDER_SECRET_KEY=.*|PROVIDER_SECRET_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=|' \
    .env
  echo "UPLOADS_DIR=$ROOT/apps/api/uploads" >> .env
fi

mkdir -p apps/api/uploads
ln -sf "$ROOT/.env" apps/api/.env

if [[ ! -f apps/web/.env ]]; then
  echo 'VITE_API_BASE_URL=http://localhost:8000' > apps/web/.env
fi

if ! psql -h localhost -p 5432 -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='textzi'" | grep -q 1; then
  psql -h localhost -p 5432 -d postgres -c "CREATE USER textzi WITH PASSWORD 'change-me-in-production' CREATEDB;"
fi
if ! psql -h localhost -p 5432 -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='textzi'" | grep -q 1; then
  psql -h localhost -p 5432 -d postgres -c "CREATE DATABASE textzi OWNER textzi;"
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r apps/api/requirements.txt

cd "$ROOT/apps/api"
"$ROOT/.venv/bin/python" -c "from app.database import Base, engine; import app.models  # noqa: F401; Base.metadata.create_all(bind=engine)"

cd "$ROOT/apps/web"
corepack enable
pnpm install --frozen-lockfile
