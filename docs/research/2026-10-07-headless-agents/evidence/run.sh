#!/bin/bash
# run.sh NAME TIMEOUT CMD... : runs CMD in toy (fresh copy), records stdout/stderr/exit/duration
S=$(dirname "$0"); name=$1; t=$2; shift 2
d=$S/w/$name; rm -rf $d; mkdir -p $S/w; cp -r $S/toy $d; cd $d
start=$(date +%s.%N)
timeout -k 5 $t "$@" > $S/out/$name.stdout 2> $S/out/$name.stderr < /dev/null
code=$?
end=$(date +%s.%N)
echo "exit=$code secs=$(awk "BEGIN{printf \"%.1f\", $end-$start}")" | tee $S/out/$name.meta
