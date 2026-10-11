#!/usr/bin/env bash
# The three projects' graphs. Run from $T after setup.sh. Prints `branch show` and lint.
set -euo pipefail
cd "$T"
OWNER=${OWNER:-Knutsi}
D=$(cd "$(dirname "$0")" && pwd)/steps
key() { python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'; }
add() {  # project title brief [after...]
  local p=$1 t=$2 f=$3; shift 3
  local after=(); for a in "$@"; do after+=(--after "$a"); done
  ./toy dplanner step add "$p" "$t" --project "$p" --agent --describe-file "$D/$f.md" --days 0.05 "${after[@]}" --json | key
}
topology() {
  ./toy dplanner topology show "$1" >/dev/null
  printf '# Parallel branches experiment\n\nProject start, then two lines of work in parallel, each on its own feature branch (a cut and a landing), joining at one final Test step. No milestones.\n' \
    | ./toy dplanner topology set "$1" --file - >/dev/null
  ./toy dplanner topology show "$1" >/dev/null
}
start() { echo 'Where the plan begins.' | ./toy dplanner step add "$1" 'Project start' --project "$1" --start --days 0 --describe-file - --json | key; }
landing_of() {  # project branch -> landing key
  ./toy dplanner branch show "$1" --project "$1" --json | python3 -c '
import json,sys; b=sys.argv[1]
for s in json.load(sys.stdin)["branches"]:
    if s["branch"]==b: print(s["land"])' "$2"
}

# --- P1-A LandThenTest (project exists; start step S1 exists) ---
P=LandThenTest
a1=$(add $P "A1 add" a1 S1); a2=$(add $P 'A2 sub' a2 "$a1")
b1=$(add $P 'B1 mul' b1 S1); b2=$(add $P 'B2 div' b2 "$b1")
./toy dplanner branch put "$a1" "$a2" --branch feature/a --project $P
./toy dplanner branch put "$b1" "$b2" --branch feature/b --project $P
la=$(landing_of $P feature/a); lb=$(landing_of $P feature/b)
t=$(add $P 'Test together' test "$la" "$lb")
echo "P1-A: A=$a1,$a2 B=$b1,$b2 landings=$la,$lb test=$t"

# --- P1-B Integration: feature/a and feature/b cut off feature/int ---
P=Integration
./toy dplanner project create $P --in plan --code "git@github.com:$OWNER/temp-dplanner-test-integration.git" \
  --checkout "$T/code/integration" --summary 'Two branches land on an integration branch, tested there, then land on main'
topology $P; s=$(start $P)
a1=$(add $P 'A1 add' a1 "$s"); a2=$(add $P 'A2 sub' a2 "$a1")
b1=$(add $P 'B1 mul' b1 "$s"); b2=$(add $P 'B2 div' b2 "$b1")
./toy dplanner branch put "$a1" "$a2" --branch feature/a --project $P
./toy dplanner branch put "$b1" "$b2" --branch feature/b --project $P
la=$(landing_of $P feature/a); lb=$(landing_of $P feature/b)
t=$(add $P 'Test together' test "$la" "$lb")
ca=$(./toy dplanner branch show $P --project $P --json | python3 -c '
import json,sys
for s in json.load(sys.stdin)["branches"]: print(s["cut"])' | tr '\n' ' ')
# shellcheck disable=SC2086
./toy dplanner branch put $ca "$a1" "$a2" "$b1" "$b2" "$la" "$lb" "$t" --branch feature/int --project $P
echo "P1-B: A=$a1,$a2 B=$b1,$b2 landings=$la,$lb test=$t"

# --- P2 TwoRepos: lib primary, app second; one stretch per repository ---
P=TwoRepos
./toy dplanner project create $P --in plan --code "git@github.com:$OWNER/temp-dplanner-test-lib.git" \
  --checkout "$T/code/lib" --summary 'One line of work in mathlib, one in calcapp, a test in calcapp using both'
./toy dplanner location add $P --role code --repository "git@github.com:$OWNER/temp-dplanner-test-app.git" \
  --label App --checkout "$T/code/app"
topology $P; s=$(start $P)
a1=$(add $P 'L1 add' l1 "$s"); a2=$(add $P 'L2 sub' l2 "$a1")
b1=$(add $P 'P1 mul command' p1 "$s"); b2=$(add $P 'P2 div command' p2 "$b1")
for x in "$b1" "$b2"; do ./toy dplanner agent workplace "$x" code:App --project $P; done
./toy dplanner branch put "$a1" "$a2" --branch feature/a --project $P
./toy dplanner branch put "$b1" "$b2" --branch feature/b --project $P
la=$(landing_of $P feature/a); lb=$(landing_of $P feature/b)
./toy dplanner agent workplace "$lb" code:App --project $P
t=$(add $P 'Test together in calcapp' ptest "$la" "$lb")
./toy dplanner agent workplace "$t" code:App --project $P
echo "P2: lib=$a1,$a2 app=$b1,$b2 landings=$la,$lb test=$t"

for P in LandThenTest Integration TwoRepos; do
  echo "===== $P"; ./toy dplanner branch show $P --project $P; ./toy dplanner project lint $P --project $P || true
done
git -C plan add -A && git -C plan commit -qm "Parallel-branches plans" && git -C plan push -qu origin main
