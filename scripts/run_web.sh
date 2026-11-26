#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 clients/web_backend.py --config config/web.json --host "${PYEXEC2_WEB_HOST:-0.0.0.0}" --port "${PYEXEC2_WEB_PORT:-8765}"
