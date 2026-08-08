#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

cd "$ROOT/api"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  . .venv/bin/activate
  pip install -r requirements.txt
else
  . .venv/bin/activate
fi

cd "$ROOT/web"
if [[ ! -d node_modules ]]; then
  npm install
fi
npm run build

cd "$ROOT/api"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8010}"
