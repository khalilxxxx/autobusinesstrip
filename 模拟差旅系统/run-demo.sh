#!/usr/bin/env bash
set -euo pipefail
demo_project_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$demo_project_dir"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, python_multipart, httpx' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.lock.txt
fi
if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && npm ci && npm run build)
fi
exec .venv/bin/python demo_control.py start --bridge
