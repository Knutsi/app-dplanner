"""The handoff aspect: its format, and the one place its shape is written down.

A handoff is what a finished step wants the next worker — usually an agent — to know:
prose, and any files worth carrying forward. Three stores, chosen by content, exactly as
``step_description`` chooses:

- the note is model state, ``module_text["step_handoff"]`` — diffable, undoable prose;
- the scope is one structured fact, ``module_data["step_handoff"]`` — written only when it
  is ``"project"``, because ``"downstream"`` is the default and absence encodes it;
- the files live in the module's area, content-addressed through
  :mod:`dplanner.domain.assets`.

Who *receives* a handoff is not stored anywhere — it is derived from the graph at read
time, in :mod:`dplanner.modules.step_handoff.handoff`.
"""

from typing import Any, Final

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "step_handoff"

# "downstream" reaches the steps that (transitively) wait on this one; "project" reaches
# every step in the project.
SCOPES: Final = ("downstream", "project")

DATA_FORMAT = ModuleDataFormat(MODULE_ID)

def read_note(step: Step) -> str:
    return step.module_text.get(MODULE_ID, "")


def enabled(step: Step) -> bool:
    """Whether this step passes something forward — the Type toggle's answer.

    A marker entry, **or** a note already written, so a step that carried a handoff before
    the aspect became toggleable keeps its tab with no data change. A step with a stored
    scope is on too: it has said something about the handoff, whatever the note holds.
    """
    return bool(step.module_data.get(MODULE_ID)) or bool(read_note(step))


def write_state(on: bool) -> dict[str, Any]:
    """The marker entry, keeping whatever scope is already stored.

    Off gives ``{}``; the note in ``module_text`` is cleared alongside it in one command,
    so one Ctrl+Z restores both.
    """
    return stamped({"on": True}, DATA_FORMAT.version) if on else {}


def read_scope(step: Step) -> str:
    """Who the handoff reaches. Absent or unreadable data reads as ``downstream``."""
    entry = step.module_data.get(MODULE_ID)
    scope = entry.get("scope") if entry else None
    return scope if scope in SCOPES else "downstream"


def write_scope(scope: str) -> dict[str, Any]:
    """The entry to store. ``downstream`` gives ``{}``, which removes the file."""
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r} (one of {', '.join(SCOPES)})")
    if scope == "downstream":
        return {}
    return stamped({"scope": scope}, DATA_FORMAT.version)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when nothing is handed forward."""
    if not read_note(step):
        return ""
    return "hands off (project)" if read_scope(step) == "project" else "hands off"


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Handoff",
    summary="What this step passes forward: notes and files for later steps' workers.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
