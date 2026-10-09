#!/bin/bash
# stub of `dplanner ask "<question>" --choice A --choice B`: records and tells the agent to stop
Q=$SCRATCH/questions
n=$(( $(ls $Q | wc -l) + 1 )); printf '%s\n' "$@" > $Q/Q$n.txt
echo "Recorded as Q$n. A person will answer it. End your turn now without doing anything else; you will be resumed with the answer."
