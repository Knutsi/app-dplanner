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

DPlanner ships at version 1 with an empty chain. The first breaking change looks like::

    Migration(
        version=2,
        note="'name' became 'title'",
        node=lambda node, raw, directory: setattr(node, "title", raw.get("name", "")),
    )
"""

from dplanner.core.formats import FormatHistory, Migration
from dplanner.domain.model import Node, Project

MIGRATIONS: tuple[Migration[Node, Project], ...] = ()

FORMAT: FormatHistory[Node, Project] = FormatHistory(MIGRATIONS, oldest_readable=1)
