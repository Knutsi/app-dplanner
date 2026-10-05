#!/usr/bin/env bash
# watch.sh [heartbeat-seconds]
# Exits (waking the director) when an agent in the run's workspace needs attention:
# blocked (a plan, a question or a permission prompt), or idle/done (finished, or waiting
# for input). An agent idle only because it waits on its own background shell ("shell still
# running") is not finished, so it is skipped. Prints the agents' states on exit.
HB=${1:-1800}
start=$(date +%s)
sleep 30
while :; do
  out=$(herdr agent list 2>/dev/null | python3 -c '
import json,sys
for a in json.load(sys.stdin)["result"]["agents"]:
    if a["workspace_id"]=="wA" and a["pane_id"]!="wA:p1":
        print(a["pane_id"], a["agent_status"], a.get("terminal_title_stripped",""))')
  attention=""
  while read -r pane state _; do
    grep -qxF "$pane" "$(dirname "$0")/parked" 2>/dev/null && continue
    case "$state" in
      blocked) attention=1 ;;
      idle|done)
        if ! herdr pane read "$pane" --source visible 2>/dev/null | grep -qE 'shells? still running|background agents? to finish|Running [0-9]+ shell'; then
          attention=1
        fi ;;
    esac
  done <<< "$out"
  if [ -n "$attention" ]; then
    echo "ATTENTION"; echo "$out"; exit 0
  fi
  if [ $(( $(date +%s) - start )) -ge "$HB" ]; then
    echo "HEARTBEAT"; echo "$out"; exit 0
  fi
  sleep 20
done
