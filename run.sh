#!/usr/bin/env bash
# Local development run (for servers use deploy/deploy.sh).
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
[ -f .env ] && set -a && . ./.env && set +a
echo "==> Aegis on http://${AEGIS_HOST:-127.0.0.1}:${AEGIS_PORT:-8080}"
exec python app.py
