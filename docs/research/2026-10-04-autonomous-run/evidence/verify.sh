#!/usr/bin/env bash
# verify.sh — pull the integration worktree and run the four checks; keeps every FAILED line.
cd /home/knut/Code/app-dplanner/.claude/worktrees/arch-integration || exit 1
git pull -q --ff-only && git log --oneline -1
QT_QPA_PLATFORM=offscreen uv run pytest -q -n 4 -p no:randomly 2>&1 | grep -E "^(FAILED|ERROR)|passed|failed" | tail -12
uv run ruff check | tail -1
uv run mypy | tail -1
uv run mypy --platform win32 | tail -1
