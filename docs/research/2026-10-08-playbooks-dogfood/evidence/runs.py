"""One line per run of the toy project, and the open questions: what a watcher needs."""

import sys
from pathlib import Path

from dplanner.domain import ledger
from dplanner.domain import questions as q

project_dir = Path(sys.argv[1])
keys = {}
for line in (project_dir / "steps").glob("*/step.json") if (project_dir / "steps").exists() else []:
    pass
for record in sorted(ledger.records(project_dir), key=lambda r: r.launched):
    turns = " ".join(f"{t.n}:{t.prompt}->{t.end or '…'}{'/' + t.why if t.why else ''}" for t in record.turns)
    tokens = sum(u.output for t in record.turns for a in t.agents for u in a.models.values()) if record.turns else 0
    print(f"{record.launched[11:19]} {record.step[:8]} {record.harness:6} {record.stage or '-':10} a{record.attempt} {record.callsign or '':14} turns[{turns}] out={tokens}{' FENCED' if record.fence else ''}{' verdict=' + str(record.verdict.get('outcome')) if record.verdict else ''}")
