"""What this machine has of DPlanner itself, as three checklist rows.

The reader is ``cli/install.py``'s :func:`~dplanner.cli.install.items` — the one this
module's dialog already refreshes on, and the one that deliberately runs no subprocess, so
a probe costs a directory read and a digest. The command and the skill are **required**:
without the first an agent cannot call DPlanner at all, and without the second it does not
know how. The launcher is a person's convenience, so it advises.

All three name the same remedy — ``install.dplanner``, this module's own action — which is
how the checklist offers a fix without importing anything: it runs the id through the
action registry and the terminal prints the command instead.
"""

from collections.abc import Callable

from dplanner.cli import install
from dplanner.cli.checklist import MachineCheck, Reading, Remedy

SkillFiles = Callable[[], dict[str, str]]

_REMEDY = Remedy(
    words="Install or update DPlanner on this machine.",
    command="dplanner install all",
    action="install.dplanner",
    verb="Install…",
)

# Required, and the label the row wears. Absent from this map means the row advises.
_REQUIRED = {install.COMMAND, install.SKILL}


def _probe(files: SkillFiles, item_id: str) -> Callable[[], Reading]:
    def read() -> Reading:
        for item in install.items(files()):
            if item.id == item_id:
                return Reading(ok=item.state == "installed", detail=item.note)
        raise KeyError(item_id)  # A piece the reader stopped reporting: a bug, not a machine.

    return read


def checks(*, files: SkillFiles) -> list[MachineCheck]:
    """The three rows. ``files`` is the generated skill, which the reader compares against."""
    return [
        MachineCheck(
            id=f"install.{item_id}",
            group="DPlanner",
            label=install.LABELS[item_id],
            probe=_probe(files, item_id),
            remedy=_REMEDY,
            required=item_id in _REQUIRED,
        )
        for item_id in (install.COMMAND, install.SKILL, install.LAUNCHER)
    ]
