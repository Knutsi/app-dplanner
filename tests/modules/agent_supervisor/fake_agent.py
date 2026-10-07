"""A fake agent CLI the supervisor tests run for real: it plays a script, one entry a turn.

    python fake_agent.py <script.json> -- <prompt>

The script is a list of turns; the n-th run of this program plays the n-th entry (the last
one again once they run out), counted in ``<script>.count``. An entry prints its ``lines``
(a recorded stream), then ``hold``s for that many seconds — silent, as a hung API is — or,
with ``spam``, prints content-free events until killed, as opencode's malformed-reply loop
did; writes ``stderr``, and exits with ``exit``. ``fence`` names a ledger record to fence
while it runs, as a takeover from another machine would.
"""

import json
import sys
import time
from pathlib import Path

script = Path(sys.argv[1])
turns = json.loads(script.read_text(encoding="utf-8"))
counter = script.with_suffix(".count")
played = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(played + 1))
turn = turns[min(played, len(turns) - 1)]

if "fence" in turn:
    record = Path(turn["fence"])
    raw = json.loads(record.read_text(encoding="utf-8"))
    raw["fence"] = {"at": "2026-10-07T12:00:00+00:00", "by": "a takeover", "why": "taken over"}
    record.write_text(json.dumps(raw), encoding="utf-8")
for line in turn.get("lines", []):
    print(line, flush=True)
    time.sleep(turn.get("pace", 0))
if turn.get("spam"):
    while True:
        print(json.dumps({"type": "system", "subtype": "api_retry"}), flush=True)
        time.sleep(0.001)
time.sleep(turn.get("hold", 0))
for line in turn.get("after", []):
    print(line, flush=True)
sys.stderr.write(turn.get("stderr", ""))
sys.exit(turn.get("exit", 0))
