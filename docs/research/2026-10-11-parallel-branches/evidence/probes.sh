#!/usr/bin/env bash
# Graph-only probes 1, 2, 4, 5 on scratch projects: refusals, lint, briefings. No agent runs
# except one launch expected to be refused before any agent starts (probe 5).
set -uo pipefail
cd "$T"
OWNER=${OWNER:-Knutsi}
id() { python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'; }
step() { local p=$1 t=$2; shift 2; local a=(); for x in "$@"; do a+=(--after "$x"); done
  echo "x" | ./toy dplanner step add "$p" "$t" --project "$p" --agent --describe-file - --days 0.05 "${a[@]}" --json | id; }
topo() { ./toy dplanner topology show "$1" >/dev/null
  echo '# Probes' | ./toy dplanner topology set "$1" --file - >/dev/null; ./toy dplanner topology show "$1" >/dev/null; }
land_of() { ./toy dplanner branch show "$1" --project "$1" --json | python3 -c '
import json,sys
for s in json.load(sys.stdin)["branches"]:
    if s["branch"]==sys.argv[1]: print(s["land"])' "$2"; }
say() { printf '\n### %s\n' "$*"; }

P=Probes
./toy dplanner project create $P --in plan --code "git@github.com:$OWNER/temp-dplanner-test-mainland.git" \
  --checkout "$T/code/mainland" --summary 'Graph probes' >/dev/null
topo $P
s=$(echo start | ./toy dplanner step add $P 'Project start' --project $P --start --days 0 --describe-file - --json | id)
./toy dplanner status set "$s" done --project $P >/dev/null
a1=$(step $P A1 "$s"); a2=$(step $P A2 "$a1"); b1=$(step $P B1 "$s"); b2=$(step $P B2 "$b1")
./toy dplanner branch put "$a1" "$a2" --branch feature/a --project $P
./toy dplanner branch put "$b1" "$b2" --branch feature/b --project $P
la=$(land_of $P feature/a); lb=$(land_of $P feature/b)

say "Probe 1: Test linked straight to A2 and B2 (before either landing)"
t1=$(step $P 'Test straight' "$a2" "$b2")
./toy dplanner branch show $P --project $P
./toy dplanner project lint $P --project $P
./toy dplanner agent run "$t1" --project $P --anyway
echo "exit $?"
./toy dplanner agent prompt "$t1" --project $P | grep -n -iE 'feature/|branch' | head -5

say "Probe 1b: the same, but via step link after the fact (is the link refused?)"
t1b=$(step $P 'Test linked later' "$la")
./toy dplanner step link "$t1b" "$b2" --project $P; echo "exit $?"

say "Probe 2: partial join — Test requires Land feature/a and B2"
t2=$(step $P 'Test partial' "$la" "$b2")
./toy dplanner branch show $P --project $P
./toy dplanner project lint $P --project $P
./toy dplanner agent prompt "$t2" --project $P | grep -n -iE 'feature/|branch|gh pr create' | head -6

say "Probe 4: a second stretch with a branch name already in use"
c1=$(step $P C1 "$s")
./toy dplanner branch put "$c1" --branch feature/a --project $P; echo "exit $?"
./toy dplanner branch show $P --project $P
./toy dplanner project lint $P --project $P

say "Probe 5: one stretch whose members are in two repositories"
Q=ProbesTwo
./toy dplanner project create $Q --in plan --code "git@github.com:$OWNER/temp-dplanner-test-lib.git" \
  --checkout "$T/code/lib" --summary 'Mixed-repo stretch probe' >/dev/null
./toy dplanner location add $Q --role code --repository "git@github.com:$OWNER/temp-dplanner-test-app.git" \
  --label App --checkout "$T/code/app" >/dev/null
topo $Q
s=$(echo start | ./toy dplanner step add $Q 'Project start' --project $Q --start --days 0 --describe-file - --json | id)
./toy dplanner status set "$s" done --project $Q >/dev/null
m1=$(step $Q 'M1 in lib' "$s"); m2=$(step $Q 'M2 in app' "$m1")
./toy dplanner agent workplace "$m2" code:App --project $Q
./toy dplanner branch put "$m1" "$m2" --branch feature/mix --project $Q
./toy dplanner project lint $Q --project $Q
# As if M1 had run in lib and recorded its branch: M2's run is no longer the stretch's first.
./toy dplanner github set "$m1" --branch agent/m1 --project $Q
./toy dplanner agent run "$m2" --project $Q --anyway; echo "exit $?"
git -C code/app ls-remote --heads origin
