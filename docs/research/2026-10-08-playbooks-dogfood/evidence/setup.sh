#!/usr/bin/env bash
# The dogfood run's toy plan, rebuilt: an isolated DPlanner (its own config dir and library),
# a tiny code repository on a throwaway private GitHub repo, a plan repository with a local
# bare remote, and one small step per playbook preset.
#
#   T=/some/scratch W=/path/to/app-dplanner/worktree bash setup.sh
#
# Every later command runs as `$T/toy <command>`, which sources env.sh: a person's terminal
# (no agent shell markers), this branch's dplanner first on PATH, Claude pinned to Opus 5.5.
# The GitHub repo is created here; delete it afterwards (`gh repo delete … --yes`, which needs
# the delete_repo scope).
set -euo pipefail
: "${T:?scratch directory}" "${W:?app-dplanner worktree}"
REPO=${REPO:-Knutsi/dplanner-dogfood-toy}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$T/config" "$T/remote" "$T/code/textstats" "$T/code/tests" "$T/plan"

cat > "$T/env.sh" <<EOF
export T=$T W=$W
for v in \$(compgen -e); do
  case "\$v" in CLAUDE_CODE_*|CLAUDECODE|AI_AGENT|CLAUDE_PID|CLAUDE_EFFORT|DPLANNER_*) unset "\$v";; esac
done
export DPLANNER_CONFIG_DIR=\$T/config DPLANNER_LIBRARY=\$T/config/library.json
export PATH=\$W/.venv/bin:\$PATH ANTHROPIC_MODEL=claude-opus-5-5
export QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME=
EOF
printf '#!/usr/bin/env bash\n. "$(dirname "$0")/env.sh"\nexec "$@"\n' > "$T/toy"
chmod +x "$T/toy"

# The code: one function and its test, and a README that says how to run the tests.
cd "$T/code"
printf '"""Tiny text statistics, the dogfood run'"'"'s toy code."""\n\n\ndef char_count(text: str) -> int:\n    """How many characters the text has."""\n    return len(text)\n' > textstats/__init__.py
printf 'from textstats import char_count\n\n\ndef test_char_count() -> None:\n    assert char_count("abc") == 3\n' > tests/test_textstats.py
printf '[project]\nname = "textstats"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n\n[tool.pytest.ini_options]\npythonpath = ["."]\n' > pyproject.toml
printf '# textstats\n\nA throwaway toy package for DPlanner'"'"'s playbook dogfood run (S21). Tests: `uv run --with pytest python -m pytest -q`.\n' > README.md
printf '__pycache__/\n.dplanner-worktrees/\n.venv/\nuv.lock\n' > .gitignore
git init -q -b main && git add -A && git commit -qm "Toy package: char_count"
gh repo create "$REPO" --private --source . --push

# The plan, and the profiles: Claude Code first (the default), then Codex.
git init -q --bare "$T/remote/plan.git"
git -C "$T/plan" init -q -b main && git -C "$T/plan" remote add origin "$T/remote/plan.git"
echo '{"format": 4, "projects": []}' > "$T/config/library.json"
cat > "$T/config/agent-profiles.json" <<'EOF'
{"format": 1, "seeded": true, "profiles": [
  {"name": "Claude Code", "agent": "claude --add-dir {run_dir} --permission-mode plan --session-id {session} {prompt}", "terminal": ""},
  {"name": "Codex", "agent": "codex {prompt}", "terminal": ""}]}
EOF
cd "$T"
./toy dplanner project create Toy --in plan --code "https://github.com/$REPO" --checkout "$T/code" \
  --summary 'textstats grows four functions and a CLI'
printf '# Toy\n\nA throwaway plan for the S21 dogfood run: one tiny step per playbook preset on the mainline, and a stretch on feature/toy (a cut, a CLI step and three coordinated steps, then a landing).\n' \
  | ./toy dplanner topology set Toy --file -
./toy dplanner topology show Toy > /dev/null  # Setting it does not count as reading it.

add() { ./toy dplanner step add Toy "$1" --agent --describe-file "$HERE/steps/$2.md" --days 0.05 ${3:+--after "$3"}; }
add 'Word count' p1
add 'Line count' p2
add 'Unique words' p3
add 'Average word length' p4
add 'Longest word' p6
add 'Split words how' p7
./toy dplanner step add Toy 'Cut feature/toy' --days 0
add 'A CLI entry point' p8 'Cut feature/toy'
add 'Sentence count' k1 'Cut feature/toy'
add 'Reading time' k2 'Sentence count'
add 'Vowel count' k3 'Cut feature/toy'
add 'Digit count' h1
./toy dplanner step add Toy 'Land feature/toy' --agent --days 0.05 --after 'A CLI entry point'
add 'Space count' h2
for s in S9 S10 S11; do ./toy dplanner step link S13 $s; done
./toy dplanner cut set S7 --branch feature/toy
./toy dplanner land set S13
for s in S1:execute S2:plan-execute-review-self S3:plan-execute-review-other S4:plan-execute-person \
  S5:plan-person-execute S6:spike S8:plan-execute-progress S9:plan-execute-coordinator \
  S10:plan-execute-coordinator S11:plan-execute-coordinator S12:execute S14:execute; do
  ./toy dplanner playbook set "${s%%:*}" "${s##*:}"
done
git -C plan add -A && git -C plan commit -qm "Toy plan" && git -C plan push -qu origin main
