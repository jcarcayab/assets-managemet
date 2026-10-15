#!/usr/bin/env bash
# Build the frontend locally, sync the code to the trading-swing host and (re)start the stack there.
#   deploy/trading-swing/deploy.sh            # deploy
#   deploy/trading-swing/deploy.sh --logs     # deploy, then follow logs
# Needs the VPN up and the "Personal" SSH key in the 1Password agent.
set -euo pipefail

HOST="${DEPLOY_HOST:-ubuntu@10.8.0.1}"
REMOTE_DIR="${DEPLOY_DIR:-patrimonio}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SSH_OPTS=(-o IdentitiesOnly=yes)
if [[ -n "${DEPLOY_KEY:-}" ]]; then SSH_OPTS+=(-i "$DEPLOY_KEY"); fi

echo "→ building frontend"
(cd "$ROOT/frontend" && npm ci --silent && npm run build --silent)

echo "→ syncing to $HOST:~/$REMOTE_DIR"
rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
  --exclude .git --exclude .idea --exclude .env --exclude '*.xlsx' \
  --exclude 'backend/.venv' --exclude 'backend/db.sqlite3' --exclude 'backend/staticfiles' --exclude '__pycache__' \
  --exclude 'frontend/node_modules' \
  --exclude 'deploy/trading-swing/.env' --exclude 'deploy/trading-swing/data' \
  "$ROOT/" "$HOST:$REMOTE_DIR/"

echo "→ building and starting on the server"
ssh "${SSH_OPTS[@]}" "$HOST" "set -e; cd $REMOTE_DIR/deploy/trading-swing
  if [ ! -f .env ]; then echo 'missing deploy/trading-swing/.env on the server' >&2; exit 1; fi
  mkdir -p data
  docker compose build web
  docker compose up -d
  docker image prune -f >/dev/null
  docker compose ps"

if [[ "${1:-}" == "--logs" ]]; then
  ssh "${SSH_OPTS[@]}" "$HOST" "cd $REMOTE_DIR/deploy/trading-swing && docker compose logs -f --tail 50"
fi
