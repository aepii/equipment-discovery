#!/usr/bin/env sh
# Build the frontend and start the web app on http://localhost:8000 (API and frontend on one port).
#   scripts/run_web.sh            live answers (needs internet and an API key in .env)
#   scripts/run_web.sh --offline  saved answers only: the example questions work with Wi-Fi off
set -e
cd "$(dirname "$0")/.."
if [ "$1" = "--offline" ]; then
  export DEMO_OFFLINE=1
  echo "Offline mode: answering only from saved answers."
fi
(cd web && { [ -d node_modules ] || npm ci; } && npm run build)
exec python -m uvicorn api.main:app --host 127.0.0.1 --port "${PORT:-8000}"
