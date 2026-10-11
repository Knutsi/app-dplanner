#!/usr/bin/env bash
# Parallel-branches experiment: an isolated DPlanner, four throwaway private GitHub repos
# (temp-dplanner-test-*), one plan repository with a local bare remote, three projects.
#   T=/scratch/exp W=/path/to/app-dplanner bash setup.sh
set -euo pipefail
: "${T:?scratch directory}" "${W:?app-dplanner checkout}"
OWNER=${OWNER:-Knutsi}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$T/config" "$T/remote" "$T/plan" "$T/code"

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

# A tiny package whose __init__ and README every branch has to touch — the shared file.
code_repo() {  # name package description
  local dir="$T/code/$1" pkg=$2
  mkdir -p "$dir/$pkg" "$dir/tests"
  cd "$dir"
  printf '"""%s"""\n\n__all__: list[str] = []\n' "$3" > "$pkg/__init__.py"
  printf 'import %s\n\n\ndef test_imports() -> None:\n    assert %s.__all__ is not None\n' "$pkg" "$pkg" > tests/test_smoke.py
  printf '[project]\nname = "%s"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n\n[tool.pytest.ini_options]\npythonpath = ["."]\n' "$pkg" > pyproject.toml
  printf '# %s\n\n%s\n\n## Functions\n\n(none yet)\n\nTests: `uv run --with pytest python -m pytest -q`.\n' "$pkg" "$3" > README.md
  printf '__pycache__/\n.dplanner-worktrees/\n.venv/\nuv.lock\n' > .gitignore
  git init -q -b main && git add -A && git commit -qm "Skeleton"
  gh repo create "$OWNER/temp-dplanner-test-$1" --private --source . --push >/dev/null
}
code_repo mainland calc "A throwaway calculator for DPlanner's parallel-branches experiment (land, then test)."
code_repo integration calc "A throwaway calculator for DPlanner's parallel-branches experiment (integration branch)."
code_repo lib mathlib "A throwaway maths library for DPlanner's two-repository experiment."
code_repo app calcapp "A throwaway command-line calculator that uses mathlib (github.com/$OWNER/temp-dplanner-test-lib)."

git init -q --bare "$T/remote/plan.git"
git -C "$T/plan" init -q -b main && git -C "$T/plan" remote add origin "$T/remote/plan.git"
echo '{"format": 4, "projects": []}' > "$T/config/library.json"
cat > "$T/config/agent-profiles.json" <<'EOF'
{"format": 1, "seeded": true, "profiles": [
  {"name": "Claude Code", "agent": "claude --add-dir {run_dir} --permission-mode plan --session-id {session} {prompt}", "terminal": ""},
  {"name": "Codex", "agent": "codex {prompt}", "terminal": ""}]}
EOF
cd "$T"
D=$HERE/steps
add() {  # project title brief [after...]
  local p=$1 t=$2 f=$3; shift 3
  local after=(); for a in "$@"; do after+=(--after "$a"); done
  ./toy dplanner step add "$p" "$t" --project "$p" --agent --describe-file "$D/$f.md" --days 0.05 "${after[@]}" --json \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
}

# P1-A: two stretches land on main, Test after both landings.
./toy dplanner project create LandThenTest --in plan --code "git@github.com:$OWNER/temp-dplanner-test-mainland.git" \
  --checkout "$T/code/mainland" --summary 'Two branches land on main, then one test step'
