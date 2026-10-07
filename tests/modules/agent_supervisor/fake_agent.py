"""A fake agent CLI the supervisor tests run for real: it plays a script, one entry a turn.

    python fake_agent.py <script.json> -- <prompt>

The script is a list of turns; the n-th run of this program plays the n-th entry (the last
one again once they run out), counted in ``<script>.count``. An entry may:

- ``pidfile``: write this process's pid there; ``child``: start a child that ignores
  SIGTERM, as a test worker might, and write *its* pid there;
- ``fence``: fence the ledger record at this path, as a takeover elsewhere would;
- ``ask``: ``{"plan": <project dir>, "question": <text>}`` — record a question on the run
  ``$DPLANNER_RUN`` names, as ``dplanner question ask`` does from inside the turn; with
  ``"answered": <words>``, somebody answers it at once, before the turn has ended;
- ``on_term``: print these lines when SIGTERM arrives, then exit 143 — a CLI's last totals;
- print its ``lines`` (a recorded stream); ``close_stdout`` then;
- ``hold`` that many seconds, silent as a hung API — or ``spam`` content-free events until
  killed, as opencode's malformed-reply loop did;
- print ``after``, write ``stderr`` and exit with ``exit``.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

script = Path(sys.argv[1])
turns = json.loads(script.read_text(encoding="utf-8"))
counter = script.with_suffix(".count")
played = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(played + 1))
turn = turns[min(played, len(turns) - 1)]

if "pidfile" in turn:
    Path(turn["pidfile"]).write_text(str(os.getpid()))
if "child" in turn:
    stubborn = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", stubborn])
    Path(turn["child"]).write_text(str(child.pid))
if "on_term" in turn:

    def last_words(*_: object) -> None:
        for line in turn["on_term"]:
            print(line, flush=True)
        os._exit(143)

    signal.signal(signal.SIGTERM, last_words)
if "fence" in turn:
    record = Path(turn["fence"])
    raw = json.loads(record.read_text(encoding="utf-8"))
    raw["fence"] = {"at": "2026-10-07T12:00:00+00:00", "by": "a takeover", "why": "taken over"}
    record.write_text(json.dumps(raw), encoding="utf-8")
if "ask" in turn:
    from dplanner.domain import questions

    asked = questions.asked(
        os.environ["DPLANNER_PROJECT"],
        "s1",
        time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        [questions.one(turn["ask"]["question"])],
        run=os.environ["DPLANNER_RUN"],
    )
    if "answered" in turn["ask"]:
        given = {turn["ask"]["question"]: turn["ask"]["answered"]}
        asked = questions.answered(asked, given, {"kind": "person", "name": "Knut"}, asked.asked)
    questions.write(Path(turn["ask"]["plan"]), asked)
for line in turn.get("lines", []):
    print(line, flush=True)
if turn.get("close_stdout"):
    sys.stdout.close()
    os.close(1)
if turn.get("spam"):
    while True:
        print(json.dumps({"type": "system", "subtype": "api_retry"}), flush=True)
        time.sleep(0.001)
time.sleep(turn.get("hold", 0))
for line in turn.get("after", []):
    print(line, flush=True)
sys.stderr.write(turn.get("stderr", ""))
sys.exit(turn.get("exit", 0))
