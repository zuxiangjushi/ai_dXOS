#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/../.."
if [ -f .env.g0 ]; then set -a; . ./.env.g0; set +a; fi
./.venv/bin/python -m deploy.g0.report "$@"
