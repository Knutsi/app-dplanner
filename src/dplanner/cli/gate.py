"""Read before you write: the topology gate, and the house documents behind the same door.

Two things have to be read before an agent writes against them, and both refuse the same
way. A project's **topology** is its own account of how its graph is shaped — what counts
as a feature here, what follows one, where the milestones fall — and an agent that edits
the graph without having read it produces a plan in the wrong shape, which is far more
expensive to correct than an empty one. A **house document** is the shape of what is
written *inside* a step: how a test body is laid out, for one. Neither is knowledge a
registry can render, and neither is worth putting in the skill, which only Claude reads.

So the CLI refuses. A verb declares which door it stands behind — ``CliCommand.edits_graph``
says how to find the project from its own arguments, ``CliCommand.reads_guide`` names the
verb that prints the document — and :func:`gated` wraps every declaring verb with one check
that runs **before the handler**, so nothing is half-done when it refuses.

What "has read" means is a digest, not a flag. ``dplanner topology show`` records the
sha256 of the text it printed, per project; ``dplanner test format`` records the sha256 of
the document it printed. The gate compares that with the text as it is now, so a topology —
or a house document this build changed — that has moved since it was read is unread again,
with no version stamp and no migration: the comparison is the check. The record is the
user's, never the plan's: it lives under ``core/config_dir.py``, which the CLI can reach
without Qt, and is never committed. A window is never gated — these are the user's own text
and this build's own document, and the gate exists for the agent driving the CLI.

A project with **no** topology refuses too: the first thing to do with a project is to say
what shape it wants, and the refusal names the verb that does it.
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from dplanner.cli.command import CliCommand, CliContext, CliError
from dplanner.core.fsio import write_atomic
from dplanner.domain.model import Project

# One file for both doors, keyed by what was read. It replaced `topology-read.json`, whose
# name stopped describing it the day a house document was read through the same record; a
# machine carrying the old file simply reads its topologies once more.
RECORD_FILE = "reads.json"
FORMAT = 2


def digest(text: str) -> str:
    """What a reading of ``text`` records: sixteen hex of sha256, the convention
    ``domain/assets.py`` content-addresses with."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _topology_key(project_id: str) -> str:
    return f"topology:{project_id}"


def _guide_key(name: str) -> str:
    return f"guide:{name}"


@dataclass(frozen=True)
class ReadRecord:
    """What this user has read on this machine: one digest per key.

    ``path=None`` records nothing and holds nothing unread — what the test suite's shared
    registry uses, so the real per-user file is never written by a test and every CLI test
    edits freely.
    """

    path: Path | None

    @property
    def records(self) -> bool:
        """False for the record that writes nothing; a gate over it refuses nothing."""
        return self.path is not None

    def note(self, key: str, text: str) -> None:
        """Remember that ``text`` is what was read for ``key``."""
        if self.path is None:
            return
        entries = self._entries()
        entries[key] = digest(text)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(
            self.path,
            json.dumps({"format": FORMAT, "read": entries}, indent=2, sort_keys=True) + "\n",
        )

    def unread(self, key: str, text: str) -> str | None:
        """Why ``text`` counts as unread under ``key`` — None when it has been read, and
        None from a record that records nothing. The phrase is the half both gates share;
        each wraps it in a sentence naming its own subject and the verb that prints it."""
        if self.path is None:
            return None
        recorded = self._entries().get(key)
        if recorded == digest(text):
            return None
        return "changed since you read it" if recorded else "has not been read on this machine"

    def _entries(self) -> dict[str, str]:
        if self.path is None or not self.path.exists():
            return {}
        try:
            data: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        entries = data.get("read") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return {}
        return {key: value for key, value in entries.items() if isinstance(value, str)}


@dataclass(frozen=True)
class TopologyGate:
    """The door a graph edit stands behind: the project's own account of its shape."""

    reads: ReadRecord
    topology_of: Callable[[Project], str]

    def record(self, project_id: str, text: str) -> None:
        """Remember that ``text`` is the topology that was read for ``project_id``."""
        self.reads.note(_topology_key(project_id), text)

    def refusal(self, project: Project) -> str | None:
        """Why a graph edit on ``project`` may not proceed — None when it may."""
        if not self.reads.records:
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
        why = self.reads.unread(_topology_key(project.id), text)
        if why is None:
            return None
        return (
            f"the topology of {title!r} {why} — read it before editing the graph: "
            f"`dplanner topology show {title!r}`"
        )


@dataclass(frozen=True)
class GuideGate:
    """The door a house document stands behind — the shape of what a verb writes.

    Unlike a topology the text is this build's and not the project's, so one reading
    covers every project on the machine and the key is the document's own.
    """

    reads: ReadRecord
    text: str
    verb: str  # The `dplanner <noun> <verb>` that prints it, named in the refusal.
    subject: str  # What it governs, as the refusal says it: "how a test is written here".

    def record(self) -> None:
        """Remember that the document as it stands has been read."""
        self.reads.note(_guide_key(self.verb), self.text)

    def refusal(self) -> str | None:
        """Why a verb that writes in this shape may not proceed — None when it may."""
        why = self.reads.unread(_guide_key(self.verb), self.text)
        if why is None:
            return None
        return f"{self.subject} {why} — read it first: `dplanner {self.verb}`"


def gated(
    command: CliCommand, topology: TopologyGate, guides: Mapping[str, GuideGate]
) -> CliCommand:
    """``command`` with the doors it declared in front of its handler. A command that
    declares neither passes through untouched, by identity. A ``reads_guide`` naming a
    document the root did not build raises here rather than running ungated."""
    resolve = command.edits_graph
    guide = guides[command.reads_guide] if command.reads_guide is not None else None
    if resolve is None and guide is None:
        return command
    inner = command.run

    def run(context: CliContext, args: Any) -> int:
        if guide is not None:
            why = guide.refusal()
            if why is not None:
                raise CliError(why)
        if resolve is not None:
            why = topology.refusal(resolve(context, args))
            if why is not None:
                raise CliError(why)
        return inner(context, args)

    return replace(command, run=run)
