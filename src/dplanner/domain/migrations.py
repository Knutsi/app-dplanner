"""The library format's history.

One tuple, appended to and never edited. The engine is in
:mod:`dplanner.core.formats`; the rules it enforces are worth restating here because this is
the file you will be tempted to break:

- A new format version is a **new entry at the end**. Never change an existing one — a
  folder written by version 1 walks the whole chain, and each step's output is the next
  step's input.
- ``node`` runs per node as it loads, with the raw dict it came from, so it can reach keys
  the model no longer has fields for. ``whole`` runs once over each finished *project* —
  the aggregate a format version covers, since every ``project.dproj`` migrates on its own.
- Bumping the version is exactly this edit. ``FORMAT.current_version`` is derived.

**Version 2 dealt every step its number.** A step's ``number`` and the project's
``last_number`` (``model.py``: minted at ``add_child``, never reused) did not exist before;
the migration numbers a version-1 project's steps in the order its ``children`` list
records — the order the project has always shown them in — and sets the mark past the
last. A ``whole`` hook, because a number is dealt per project and a per-node hook cannot
see its siblings.
"""

from dplanner.core.formats import FormatHistory, Migration
from dplanner.domain.model import Node, Project, next_number


def _deal_numbers(project: Project) -> None:
    for step in project.steps:
        if not step.number:
            step.number = next_number(project)
            project.last_number = step.number


MIGRATIONS: tuple[Migration[Node, Project], ...] = (
    Migration(
        version=2,
        note="every step carries a per-project number; the project keeps the high-water mark",
        whole=_deal_numbers,
    ),
)

FORMAT: FormatHistory[Node, Project] = FormatHistory(MIGRATIONS, oldest_readable=1)
