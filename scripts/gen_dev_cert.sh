#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p config
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout config/server.key -out config/server.crt \
  -days 365 -subj "/CN=pyexec2-dev" >/dev/null 2>&1
chmod 600 config/server.key
echo "Generated config/server.crt and config/server.key (development only)."
