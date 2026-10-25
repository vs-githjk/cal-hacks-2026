#!/usr/bin/env bash
# Register every running mailbox agent on Agentverse: for each agent port, run agents/connect.py <port>.
#
#   set -a; . agents/.env; set +a            # or export AGENTVERSE_API_KEY=... yourself; the key is never printed
#   python3 scripts/launch.py up --mailbox   # start the agents in mailbox mode first (each needs its private *_AGENT_SEED)
#   scripts/register_agents.sh               # all nine agents
#   scripts/register_agents.sh caller pulse  # only these
#   scripts/register_agents.sh --list        # print the agents and their ports, change nothing
#
# Agents (name: port): buyer 8001, advocate 8003, shield 8004, caller 8006, seller_1 8011, seller_3 8013, seller_5 8015,
# seller_6 8016, pulse 8018. Exit 0: every agent registered. Exit 1: at least one did not (the rest are still tried).
# Exit 2: a refusal before anything ran (no AGENTVERSE_API_KEY, unknown agent name, no python for connect.py).
# Test hooks: REGISTER_PYTHON and REGISTER_CONNECT replace the interpreter and connect.py.
set -u -o pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="${REGISTER_PYTHON:-$ROOT/agents/.venv/bin/python}"
CONNECT="${REGISTER_CONNECT:-$ROOT/agents/connect.py}"
ALL="buyer advocate shield caller seller_1 seller_3 seller_5 seller_6 pulse"

port_of() {
  case "$1" in
    buyer) echo 8001 ;;
    advocate) echo 8003 ;;
    shield) echo 8004 ;;
    caller) echo 8006 ;;
    seller_1) echo 8011 ;;
    seller_3) echo 8013 ;;
    seller_5) echo 8015 ;;
    seller_6) echo 8016 ;;
    pulse) echo 8018 ;;
    *) return 1 ;;
  esac
}

if [ "${1:-}" = "--list" ]; then
  for name in $ALL; do printf '%-9s %s\n' "$name" "$(port_of "$name")"; done
  exit 0
fi
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
fi

targets="${*:-$ALL}"
for name in $targets; do
  if ! port_of "$name" >/dev/null; then
    echo "unknown agent '$name'. Known agents: $ALL" >&2
    exit 2
  fi
done

if [ -z "${AGENTVERSE_API_KEY:-}" ]; then
  echo "AGENTVERSE_API_KEY is not set, so nothing was registered." >&2
  echo "Load it into this shell without printing it:  set -a; . agents/.env; set +a   (then run this again)" >&2
  exit 2
fi
if [ ! -x "$PY" ]; then
  echo "no python at $PY. Create agents/.venv first:  python3 scripts/launch.py up   (it builds the venv)" >&2
  exit 2
fi

failed=0
for name in $targets; do
  port="$(port_of "$name")"
  out="$("$PY" "$CONNECT" "$port" 2>&1)"
  code=$?
  out="${out//"$AGENTVERSE_API_KEY"/[hidden]}"          # connect.py never echoes the key; this is a second lock
  last="$(printf '%s\n' "$out" | tail -n 1 | cut -c1-300)"
  if [ "$code" -eq 0 ] && printf '%s' "$out" | grep -Eq '"success": *true'; then
    printf 'ok      %-9s port %s  %s\n' "$name" "$port" "$last"
  else
    printf 'FAILED  %-9s port %s  %s\n' "$name" "$port" "$last"
    echo "        is the agent running in mailbox mode on port $port? (python3 scripts/launch.py up --mailbox)" >&2
    failed=$((failed + 1))
  fi
done

if [ "$failed" -ne 0 ]; then
  echo "$failed agent(s) not registered." >&2
  exit 1
fi
echo "all registered. Open https://agentverse.ai/agents to see them."
