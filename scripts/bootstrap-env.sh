#!/usr/bin/env bash
# scripts/bootstrap-env.sh — kill every default credential in the quickstart.
# `make up` calls this when .env is missing; values are generated, never
# committed, never shared between checkouts.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  echo ".env exists — refusing to overwrite"
  exit 0
fi

rand() { openssl rand -hex 24; }

cat > .env <<EOF
# generated $(date -u +%FT%TZ) by scripts/bootstrap-env.sh — DO NOT COMMIT
ENV=dev
DEV_BEARER_TOKEN=$(rand)
BROKER_USERNAME=broker
BROKER_PASSWORD=$(rand)
S3_ACCESS_KEY=sovereign-$(openssl rand -hex 4)
S3_SECRET_KEY=$(rand)
CLICKHOUSE_PASSWORD=$(rand)
EOF
chmod 600 .env
echo "wrote .env with generated credentials"
