"""The agent skill as a notice source: out of date, or not installed. Qt-free.

The check is ``cli/skill.py``'s own ``status`` — the files this build renders against the
files on disk — which is what the Tools ▸ Agent Skill dialog's button label reads too.
Rendering the files costs a good part of a second, so the source never does it: the
install module renders once, off the GUI thread, and this reads the cache through
``files``; ``prepare`` asks for that render, and the module says ``changed`` when it lands.
Until then the source stands for nothing rather than guessing.
"""

from collections.abc import Callable

from dplanner.cli.skill import status, target_dir
from dplanner.core.signals import Signal
from dplanner.domain.notice import Notice

SOURCE_ID = "install.skill"

STALE = Notice(
    "stale",
    "Agent skill is out of date",
    "Installed from another build; Update rewrites it.",
    ("action", "install.skill"),
    where="Agent skill",
)
MISSING = Notice(
    "missing",
    "Agent skill is not installed",
    "Install it so a coding agent can drive DPlanner.",
    ("action", "install.skill"),
    where="Agent skill",
)


class SkillNoticeSource:
    id = SOURCE_ID
    label = "Agent skill"

    def __init__(
        self, files: Callable[[], dict[str, str] | None], prepare: Callable[[], None]
    ) -> None:
        self._files = files
        self._prepare = prepare
        self.changed: Signal[()] = Signal("notices.skill.changed")

    def start(self) -> None:
        self._prepare()

    def stop(self) -> None:
        pass

    def scan(self) -> list[Notice]:
        files = self._files()
        if files is None:
            return []
        state = status(files, target_dir(user=True))
        if state == "stale":
            return [STALE]
        if state == "missing":
            return [MISSING]
        return []
