#!/usr/bin/env bash
# Provision a Neon project and wire up .env. Idempotent: re-running reuses the
# project if it already exists.
#
#   ./setup_neon.sh [project-name]
#
# Requires the Neon CLI, authenticated:  npm i -g neonctl && neon auth
set -euo pipefail

NAME="${1:-harness-production-rag}"
HERE="$(cd "$(dirname "$0")" && pwd)"

ORG=$(neon orgs list -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')
echo "org: $ORG"

EXISTING=$(neon projects list --org-id "$ORG" -o json \
  | python3 -c "import json,sys; print(next((p['id'] for p in json.load(sys.stdin) if p['name']=='$NAME'), ''))")

if [ -n "$EXISTING" ]; then
  echo "reusing project $EXISTING"
  DSN=$(neon connection-string --project-id "$EXISTING")
else
  echo "creating project $NAME"
  DSN=$(neon projects create --name "$NAME" --org-id "$ORG" --pg-version 17 -o json \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["connection_uris"][0]["connection_uri"])')
fi

KEY=$(grep -s '^MISTRAL_API_KEY=' "$HERE/.env" | cut -d= -f2- || true)
printf 'MISTRAL_API_KEY=%s\nDATABASE_URL=%s\n' "$KEY" "$DSN" > "$HERE/.env"
echo "wrote $HERE/.env  (gitignored)"

python "$HERE/db.py"
echo
echo "next:  python ingest.py  &&  python main.py \"what is the refund window?\""
