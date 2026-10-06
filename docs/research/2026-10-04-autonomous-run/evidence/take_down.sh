#!/usr/bin/env bash
# take_down.sh <name> — after a step is merged: close its herdr tab, remove its worktree and
# local branch (the remote branch and the PR keep the history).
set -uo pipefail
NAME=$1
R=/tmp/claude-1000/-home-knut-Code-app-dplanner/3e05a52a-1fbf-409e-afe6-ee63d9cd3417/scratchpad/run
REPO=/home/knut/Code/app-dplanner
TAB=$(cat "$R/$NAME/tab"); WT=$(cat "$R/$NAME/worktree"); BRANCH=$(cat "$R/$NAME/branch")
herdr tab close "$TAB" >/dev/null 2>&1 || echo "tab $TAB already gone"
cd "$REPO"
git worktree remove --force "$WT" 2>&1 | tail -1
git branch -D "$BRANCH" >/dev/null 2>&1 || true
echo "- $(date '+%Y-%m-%d %H:%M:%S') **take-down** $NAME: tab $TAB closed, worktree removed" >> "$R/log.md"
echo "down: $NAME"
