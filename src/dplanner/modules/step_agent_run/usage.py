"""The agent-usage aspect: what the agent runs on a step have consumed, run by run.

Where the run aspect (``aspect.py``) says where an agent *stands* and is cleared when the
shell ends, this one is what stays behind: one row per run — the harness, the session it
was, when it ended, and the tokens it consumed, read back from the harness's own records
(:mod:`dplanner.domain.agents`). The totals are never stored: :func:`totals` sums the rows,
so a step's cost is a derivation over a list a person can read, and a row recorded twice
(a window that read the record at exit and a person who ran ``dplanner usage record`` for
the same session) is one row, keyed by session, last write wins.

The **row is appended when the shell ends**, by the window that launched it — directly,
off the undo stack, with its own origin, exactly as the exit is recorded: a token count is
an external fact, and Ctrl+Z must not erase what an agent already consumed. From the
terminal, ``dplanner usage record`` writes the same row, through the same harness
readers, for a run the window did not launch; ``usage show`` and ``usage list`` read
them back. Absence is the default — no agent has run here.
"""

from collections.abc import Sequence
from typing import Any, Final

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.agents import Usage
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step, StepId, now_stamp

MODULE_ID = "agent_usage"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

# The origin a recorded row carries: no view claims it, so every surface treats the
# write as foreign and repaints — the launch stamp's pattern.
USAGE_ORIGIN: Final[object] = object()


def rows(step: Step) -> list[dict[str, Any]]:
    """The step's usage rows as stored: ``harness``, ``session``, ``input``, ``output``,
    ``details``, ``ended``. A row this build cannot read is skipped, never a crash."""
    entry = step.module_data.get(MODULE_ID) or {}
    stored = entry.get("runs")
    if not isinstance(stored, list):
        return []
    return [row for row in stored if isinstance(row, dict) and _readable(row)]


def _readable(row: dict[str, Any]) -> bool:
    return all(isinstance(row.get(key), int) for key in ("input", "output"))


def totals(step: Step) -> Usage | None:
    """Everything the step's runs consumed, or None when nothing has been recorded."""
    recorded = rows(step)
    if not recorded:
        return None
    return Usage(
        input=sum(int(row["input"]) for row in recorded),
        output=sum(int(row["output"]) for row in recorded),
    )


def row_for(harness: str, session: str, usage: Usage, ended: str = "") -> dict[str, Any]:
    return {
        "harness": harness,
        "session": session,
        "input": usage.input,
        "output": usage.output,
        "details": dict(usage.details),
        "ended": ended or now_stamp(),
    }


def with_row(step: Step, row: dict[str, Any]) -> dict[str, Any]:
    """The step's entry with ``row`` added — replacing the row of the same session, so
    a record read twice is one row."""
    kept = [
        existing
        for existing in rows(step)
        if not (row["session"] and existing.get("session") == row["session"])
    ]
    return stamped({"runs": [*kept, row]}, DATA_FORMAT.version)


def record(library: Library, step_id: StepId, row: dict[str, Any]) -> bool:
    """Append a run's row — directly, off the undo stack, with this aspect's origin.

    The row records an external fact: the tokens were consumed whether or not anybody
    presses Ctrl+Z. False, and no write, when the step is gone.
    """
    if not library.has(step_id):
        return False
    step = library.step(step_id)
    SetModuleDataCommand(step_id, MODULE_ID, with_row(step, row), view_origin=USAGE_ORIGIN).redo(
        library
    )
    return True


def words(usage: Usage) -> str:
    """``12.3k in · 1.2k out`` — how a row or a chip says it."""
    return f"{_short(usage.input)} in · {_short(usage.output)} out"


def _short(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when no run has been recorded."""
    total = totals(step)
    return "" if total is None else f"tokens: {words(total)}"


def forget_for_paste(_project: Project, steps: Sequence[Step]) -> None:
    """A copied step carries no usage: the tokens were spent on the original."""
    for step in steps:
        step.module_data.pop(MODULE_ID, None)


SPEC = AspectSpec(
    id=MODULE_ID,
    label="Agent usage",
    summary="What the agent runs on a step consumed: input and output tokens per run,"
    " read back from the agent CLI's own records when the shell ends.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
