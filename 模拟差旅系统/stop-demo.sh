#!/usr/bin/env bash
set -euo pipefail
demo_project_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$demo_project_dir"
exec .venv/bin/python demo_control.py stop
