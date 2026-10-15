#!/bin/sh
# Forward one hook event (JSON on stdin) to the local Overture board.
# Gives up after one second and always exits 0, so a stopped board never
# slows down or fails the agent session.
tool="${1:-claude}"
port="${AGENT_BOARD_PORT:-8787}"
curl -s -m 1 -o /dev/null -X POST -H 'Content-Type: application/json' \
  --data-binary @- "http://127.0.0.1:${port}/api/v1/unified/sessions/events?tool=${tool}" \
  >/dev/null 2>&1 || true
exit 0
