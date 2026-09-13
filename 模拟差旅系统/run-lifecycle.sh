#!/usr/bin/env bash
set -euo pipefail
lifecycle_project_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$lifecycle_project_dir"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, python_multipart, httpx, yaml' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.lock.txt
fi
(cd frontend && npm ci && npm run build)
exec .venv/bin/python lifecycle_control.py start
