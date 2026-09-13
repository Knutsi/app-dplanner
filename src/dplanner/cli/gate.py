"""The topology gate: a graph-editing verb runs only after the topology has been read.

A project's **topology** is its own account of how its graph is shaped — what counts as
a feature here, what follows one, where the milestones fall. An agent that edits the graph
without having read it produces a plan in the wrong shape, and a wrong shape is far more
expensive to correct than an empty one. So the CLI refuses: a verb that reshapes a graph
declares it (``CliCommand.edits_graph`` says how to find the project from its own
arguments), and this module wraps every declaring verb with one check that runs **before
the handler** — nothing is half-done when it refuses.

What "has read" means is a digest, not a flag. ``dplanner topology show`` records the
sha256 of the text it printed, per project, in a per-user, per-machine file; the gate
compares that with the text as it is now. A topology that changed since it was read is
unread again, with no version stamp and no migration — the comparison is the check. The
record is the user's, never the plan's: it lives under ``core/config_dir.py``, which the
CLI can reach without Qt, and is never committed. A window is never gated — the topology
is the user's own text, and the gate exists for the agent driving the CLI.

A project with **no** topology refuses too: the first thing to do with a project is to say
what shape it wants, and the refusal names the verb that does it.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.core.fsio import write_atomic
from dplanner.domain.model import Project

RECORD_FILE = "topology-read.json"
FORMAT = 1


def digest(text: str) -> str:
    """What a reading of ``text`` records: sixteen hex of sha256, the convention
    ``domain/assets.py`` content-addresses with."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class TopologyGate:
    """The gate over one record file. ``record_path=None`` is a gate that refuses nothing
    and records nothing — what the test suite's shared registry uses, so the real
    per-user file is never written by a test."""

    record_path: Path | None
    topology_of: Callable[[Project], str]

    def record(self, project_id: str, text: str) -> None:
        """Remember that ``text`` is what was read for ``project_id``."""
        if self.record_path is None:
            return
        entries = self._read()
        entries[project_id] = digest(text)
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(
            self.record_path,
            json.dumps({"format": FORMAT, "read": entries}, indent=2, sort_keys=True) + "\n",
        )

    def refusal(self, project: Project) -> str | None:
        """Why a graph edit on ``project`` may not proceed — None when it may."""
        if self.record_path is None:
            return None
        text = self.topology_of(project)
        title = project.title or project.id
        if not text.strip():
            # Both verbs, in the order to run them: `topology show` prints the house
            # default, which is what a topology written before reading it gets wrong.
            return (
                f"{title!r} has no topology yet — read the default shape, then say how "
                f"this graph is shaped: `dplanner topology show {title!r}`, then "
                f"`dplanner topology set {title!r} --file -`"
            )
        recorded = self._read().get(project.id)
        if recorded == digest(text):
            return None
        why = "changed since you read it" if recorded else "has not been read on this machine"
        return (
            f"the topology of {title!r} {why} — read it before editing the graph: "
            f"`dplanner topology show {title!r}`"
        )

    def _read(self) -> dict[str, str]:
        if self.record_path is None or not self.record_path.exists():
            return {}
        try:
            data: Any = json.loads(self.record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        entries = data.get("read") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return {}
        return {key: value for key, value in entries.items() if isinstance(value, str)}


def gated(command: CliCommand, gate: TopologyGate) -> CliCommand:
    """``command`` with the gate in front of its handler. A command that does not declare
    ``edits_graph`` passes through untouched, by identity."""
    resolve = command.edits_graph
    if resolve is None:
        return command
    inner = command.run

    def run(context: CliContext, args: Any) -> int:
        project = resolve(context, args)
        why = gate.refusal(project)
        if why is not None:
            raise CliError(why)
        return inner(context, args)

    return replace(command, run=run)
