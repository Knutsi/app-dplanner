# Working on DPlanner

`CLAUDE.md` is the rulebook: read it first, whichever agent you are. It is the core, and the
rules for each area of the tree are in `.claude/rules/`, which only Claude Code loads by itself —
so run `uv run python scripts/rules.py for <paths>` before you plan a change and
`uv run python scripts/rules.py diff` before you finish, and read everything they print.
