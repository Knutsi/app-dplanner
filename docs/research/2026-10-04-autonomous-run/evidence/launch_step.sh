#!/usr/bin/env bash
# launch_step.sh <step-id> <name> <tab label>
# Prepares the step's worktree as Run Agent would, writes its briefing, and starts a Claude
# agent (plan mode) in a new tab of the run's herdr workspace. Prints the agent's pane id.
set -euo pipefail
ID=$1; NAME=$2; LABEL=$3
R=/tmp/claude-1000/-home-knut-Code-app-dplanner/3e05a52a-1fbf-409e-afe6-ee63d9cd3417/scratchpad/run
REPO=/home/knut/Code/app-dplanner
WS=wA
export DPLANNER_PROJECT=d4ba534a
LOG=$R/log.md
stamp() { date '+%Y-%m-%d %H:%M:%S'; }

mkdir -p "$R/$NAME"
cd /tmp
dplanner agent prompt "$ID" > "$R/$NAME/briefing.md"
SLUG=$(grep -o '\.dplanner-worktrees/[^`]*' "$R/$NAME/briefing.md" | head -1 | sed 's#\.dplanner-worktrees/##')
BRANCH=$(grep -o 'must print `[^`]*' "$R/$NAME/briefing.md" | head -1 | sed 's#must print `##')
[ -n "$SLUG" ] && [ -n "$BRANCH" ] || { echo "could not read worktree/branch from briefing" >&2; exit 1; }
WT=$REPO/.dplanner-worktrees/$SLUG

cd "$REPO"
git worktree prune >/dev/null 2>&1 || true
EX="$(git rev-parse --git-common-dir)/info/exclude"
grep -qxF '/.dplanner-worktrees/' "$EX" 2>/dev/null || echo '/.dplanner-worktrees/' >> "$EX"
git fetch --quiet origin
if [ ! -e "$WT" ]; then
  if git show-ref --verify --quiet "refs/heads/$BRANCH" || git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    git worktree add --quiet "$WT" "$BRANCH"   # an existing branch (a landing works on the feature branch itself)
  else
    git worktree add --quiet -b "$BRANCH" "$WT" origin/refactor/arch-revision
  fi
fi

TAB=$(herdr tab create --workspace "$WS" --cwd "$WT" --label "$LABEL" \
  --env DPLANNER_PROJECT=d4ba534a --env "DPLANNER_RUN=$R/$NAME" --no-focus)
PANE=$(echo "$TAB" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["root_pane"]["pane_id"])')
TABID=$(echo "$TAB" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["tab"]["tab_id"])')
echo "$TABID" > "$R/$NAME/tab"; echo "$PANE" > "$R/$NAME/pane"; echo "$WT" > "$R/$NAME/worktree"
echo "$ID" > "$R/$NAME/step"; echo "$BRANCH" > "$R/$NAME/branch"

herdr agent start "$NAME" --kind claude --pane "$PANE" --timeout 60000 -- \
  --permission-mode plan --add-dir "$R/$NAME" >/dev/null
herdr agent prompt "$NAME" "Your briefing for this DPlanner step is the file $R/$NAME/briefing.md — read all of it first, then plan the work and carry it out. You are in the step's worktree already." >/dev/null

cd /tmp
dplanner github set "$ID" --branch "$BRANCH" >/dev/null
dplanner status set "$ID" in-progress >/dev/null
echo "- $(stamp) **launch** $NAME ($ID) in $TABID/$PANE, worktree $SLUG, branch $BRANCH" >> "$LOG"
echo "$PANE"
