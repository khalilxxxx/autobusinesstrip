#!/usr/bin/env bash
set -euo pipefail
lifecycle_project_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$lifecycle_project_dir"
exec .venv/bin/python lifecycle_control.py stop
