#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 run.py --host "${PYEXEC2_HOST:-0.0.0.0}" --port "${PYEXEC2_PORT:-18080}"
