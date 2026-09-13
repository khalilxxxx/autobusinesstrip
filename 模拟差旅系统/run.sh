#!/usr/bin/env bash
set -euo pipefail
project_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$project_dir"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, python_multipart, httpx' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.lock.txt
fi
if [ ! -f frontend/dist/index.html ] && [ -f frontend/package.json ]; then
  (cd frontend && npm ci && npm run build)
fi
exec .venv/bin/python -m uvicorn mock_travel.app:create_app --factory \
  --host "${MOCK_HOST:-127.0.0.1}" --port "${MOCK_PORT:-8766}" "$@"
