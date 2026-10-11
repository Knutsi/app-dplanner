"""The playbook aspect: which playbook a step runs, and the project's defaults.

One namespace on two kinds of node. On a step, ``{"playbook": <preset id>}`` with optional
overrides — ``rounds`` (every gate's cap) and ``reviewer`` (the reviewer role's harness id).
On the project, ``{"default": <preset id>, "landing": <preset id>}``. Absence encodes the
default throughout, so a later change of default reaches every step that never chose.

Which playbook a step runs (:func:`resolve`): its own choice; else, on a branch landing, the
project's landing default — *Land* unless the project names another; else the
project's default; else none, and the step has Run Agent as it always had.
"""

from dataclasses import dataclass
from typing import Any, Literal

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Project, Step
from dplanner.modules.step_playbook.presets import LANDING_DEFAULT, MAX_ROUNDS, Playbook, preset
from dplanner.planning.branches import is_land

MODULE_ID = "step_playbook"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

Source = Literal["step", "landing", "project", "none"]


@dataclass(frozen=True)
class Choice:
    """A step's own choice. ``rounds`` and ``reviewer`` are None for the default."""

    playbook: Playbook
    rounds: int | None = None
    reviewer: str | None = None


@dataclass(frozen=True)
class Defaults:
    """A project's defaults: ``default`` None is no playbook — Run Agent."""

    default: Playbook | None = None
    landing: Playbook = LANDING_DEFAULT


@dataclass(frozen=True)
class Resolved:
    playbook: Playbook | None
    source: Source


def read(step: Step) -> Choice | None:
    """The step's own choice; None for none, or for a preset this build does not know."""
    entry = step.module_data.get(MODULE_ID) or {}
    named = entry.get("playbook")
    playbook = preset(named) if isinstance(named, str) else None
    if playbook is None:
        return None
    reviewer = entry.get("reviewer")
    return Choice(
        playbook,
        rounds=_rounds_in(entry.get("rounds")),
        reviewer=reviewer if isinstance(reviewer, str) and reviewer else None,
    )


def _rounds_in(value: object) -> int | None:
    """A round cap read back — a whole number from 1 to the most — or None."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value) if float(value).is_integer() and 1 <= value <= MAX_ROUNDS else None


def write(choice: Choice | None) -> dict[str, Any]:
    """The step's entry; ``{}`` — no file — for the default."""
    if choice is None:
        return {}
    entry: dict[str, Any] = {"playbook": choice.playbook.id}
    if choice.rounds is not None:
        entry["rounds"] = float(choice.rounds)  # A number on disk is a float (FORMAT.md).
    if choice.reviewer is not None:
        entry["reviewer"] = choice.reviewer
    return stamped(entry, DATA_FORMAT.version)


def read_project(project: Project) -> Defaults:
    entry = project.module_data.get(MODULE_ID) or {}
    default = entry.get("default")
    landing = entry.get("landing")
    found = preset(landing) if isinstance(landing, str) else None
    return Defaults(
        default=preset(default) if isinstance(default, str) else None,
        landing=found if found is not None else LANDING_DEFAULT,
    )


def write_project(defaults: Defaults) -> dict[str, Any]:
    """The project's entry, naming only what differs from the defaults."""
    entry: dict[str, Any] = {}
    if defaults.default is not None:
        entry["default"] = defaults.default.id
    if defaults.landing != LANDING_DEFAULT:
        entry["landing"] = defaults.landing.id
    return stamped(entry, DATA_FORMAT.version)


def resolve(step: Step, project: Project) -> Resolved:
    """Which playbook ``step`` runs, and where that choice was made."""
    choice = read(step)
    return Resolved(choice.playbook, "step") if choice is not None else inherited(step, project)


def inherited(step: Step, project: Project) -> Resolved:
    """What ``step`` runs when it has no choice of its own — what *Default* means for it."""
    defaults = read_project(project)
    if is_land(step):
        return Resolved(defaults.landing, "landing")
    if defaults.default is not None:
        return Resolved(defaults.default, "project")
    return Resolved(None, "none")


def summary(step: Step) -> str:
    choice = read(step)
    if choice is None:
        return ""
    words = [choice.playbook.name]
    if choice.rounds is not None:
        words.append(f"{choice.rounds} round{'s' if choice.rounds != 1 else ''}")
    if choice.reviewer is not None:
        words.append(f"reviewer {choice.reviewer}")
    return " · ".join(words)


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Playbook",
    summary="Which playbook runs the step — plan, execute and the gates that judge the work — "
    "with its round cap and reviewer; absent, the project's default.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
