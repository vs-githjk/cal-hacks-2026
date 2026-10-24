#!/bin/sh
# #295: publish the Tech Bazaar market to Maincloud, seed it and give the demo identities their roles.
# Vidyut runs this once from his Mac: his `spacetime login` identity publishes, so it is the owner. Nothing here runs in CI.
#
#   SPACETIMEDB_DB=tech-bazaar sh scripts/deploy_maincloud.sh            # dry run: prints the steps, calls nothing
#   SPACETIMEDB_DB=tech-bazaar sh scripts/deploy_maincloud.sh --go       # does it
#
# It never deletes data: there is no --delete-data and no --yes=all on the publish, so a schema change that needs a wipe
# stops with spacetime's own error instead of clearing the shared market (#313). Tokens go to .tokens/<db>@<host>/
# (gitignored), never to the local .tokens/.
set -eu

DB="${SPACETIMEDB_DB:-tech-bazaar}"
SERVER="maincloud"
HOST="maincloud.spacetimedb.com"
HTTP="https://$HOST"
TOKENS=".tokens/$DB@$HOST"
GO="${1:-}"

case "$DB" in *[!a-z0-9-]*|"") echo "SPACETIMEDB_DB must be lowercase letters, digits and -"; exit 2 ;; esac
cd "$(dirname "$0")/.."

run() {
  echo "+ $*"
  if [ "$GO" = "--go" ]; then "$@"; fi
}

check() {   # a step that reads back what the last step did; in a dry run it is only printed
  echo "  check: $1"
  if [ "$GO" = "--go" ]; then sh -c "$2" || { echo "  CHECK FAILED: $1"; exit 1; }; fi
}

echo "Tech Bazaar market -> Maincloud database $DB ($HTTP)"
[ "$GO" = "--go" ] || echo "(dry run: add --go to run these)"

run spacetime publish -s "$SERVER" -p ./market/spacetimedb "$DB"
check "the module answers" "spacetime sql -s $SERVER $DB 'SELECT * FROM owner' >/dev/null"

run spacetime call -s "$SERVER" "$DB" seed_demo
check "seed_demo made the pair code" "spacetime sql -s $SERVER $DB 'SELECT code FROM pair_code' | grep -q ."

mkdir -p "$TOKENS"
run env SPACETIMEDB_SERVER="$SERVER" SPACETIMEDB_HTTP="$HTTP" SPACETIMEDB_DB="$DB" \
  python3 market/scripts/setup_roles.py "$TOKENS"
check "the referee and buyer tokens exist" "test -s $TOKENS/referee.json && test -s $TOKENS/buyer-vidyut.json"
check "roles are in the market" "spacetime sql -s $SERVER $DB 'SELECT role FROM role' | grep -q referee"

echo "Done. In the Lane D env file set:"
echo "  SPACETIMEDB_SERVER=$SERVER  SPACETIMEDB_HTTP=$HTTP  SPACETIMEDB_DB=$DB"
echo "  NEXT_PUBLIC_SPACETIMEDB_URI=wss://$HOST  NEXT_PUBLIC_SPACETIMEDB_DB=$DB"
echo "then: python3 scripts/launch.py up --maincloud"
