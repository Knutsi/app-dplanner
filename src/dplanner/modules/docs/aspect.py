"""Two aspects, one story: the documentation a step contributes, and the document a
collector compiles out of everything it gathers.

**A fragment is what a step adds; a compiled document is what a feature or a milestone
makes of them.** They are two aspects rather than one because a node holds exactly one prose
document per module id (``FORMAT.md``), and a feature legitimately has both — its own note,
and the document compiled from the four steps behind it. Two ids, two ``.md`` files, and
both diff line by line.

There is deliberately **no step kind for compiling**. A feature and a milestone already *are*
the collectors the graph defines, so compiling is something a collector does, not a node
somebody has to remember to create. What a collector compiles from is
:mod:`dplanner.modules.docs.collect`, never stored.

The stores, chosen by content, exactly as ``step_description`` chooses:

- prose is model state — ``module_text["docs"]`` and ``module_text["docs_compiled"]`` —
  diffable, undoable, and it gets the text stack a JSON value would not;
- ``module_data["docs"]`` is the fragment's ``{"on": true}`` marker, and
  ``module_data["docs_compiled"]`` is what the last compile recorded, **including the digest
  of what it read** — the one fact staleness is derived from;
- images live in the module's area, content-addressed through :mod:`dplanner.domain.assets`.

The ``docs`` namespace spans node kinds, which ``FORMAT.md`` sanctions and
``step_agent_instruction`` already does: beside a **project**, ``modules/docs.md`` is the
standing documentation style, prepended to every compile. A project does no work, so there is
no documentation-of-its-own for that to collide with.
"""

from collections.abc import Sequence
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.assets import (
    AssetLocation,
    AssetSource,
    AssetUse,
    area_assets,
    asset_references,
)
from dplanner.domain.model import Library, Node, NodeId, Project, Step
from dplanner.domain.store import FilesFor

MODULE_ID = "docs"
COMPILED_ID = "docs_compiled"

DATA_FORMAT = ModuleDataFormat(MODULE_ID)
COMPILED_FORMAT = ModuleDataFormat(COMPILED_ID)


# -- the fragment ------------------------------------------------------------------------------


def read(node: Node) -> str:
    """A step's documentation — or, on a project, its standing documentation style."""
    return node.module_text.get(MODULE_ID, "")


def enabled(step: Step) -> bool:
    """Whether this step documents something — the Type toggle's answer.

    **Absence means off**: most steps document nothing, so the entry records the claim. A
    marker entry *or* prose already written, so documentation the CLI wrote before anybody
    touched the toggle still shows its tab, with no migration.
    """
    return bool(step.module_data.get(MODULE_ID)) or bool(read(step))


def write_state(on: bool) -> dict[str, Any]:
    """The marker entry. Off gives ``{}``, which removes the file."""
    return stamped({"on": True}, DATA_FORMAT.version) if on else {}


def asset_source() -> AssetSource:
    """This module's slice of the project's asset catalog.

    "Used" is answered project-wide by name, not per area: a *compiled* document renders
    images from its source steps' areas (``framework/markdown_view.py`` asks each area in
    turn, exact because names are content-addressed), so a fragment's image may be needed
    by a collector's compiled text long after the fragment dropped it. Any docs-area copy
    whose name a fragment, a compiled document or the standing style still references is
    therefore used — and the use names the *referencing* node, which is what a "used by"
    list should say.
    """

    def scan(
        _library: Library, project: Project, files: FilesFor
    ) -> Sequence[AssetLocation]:
        referenced: dict[str, list[AssetUse]] = {}

        def note(names: list[str], use: AssetUse) -> None:
            for name in names:
                referenced.setdefault(name, []).append(use)

        note(
            asset_references(read(project)),
            AssetUse("project", project.id, project.title, "documentation style"),
        )
        for step in project.steps:
            note(
                asset_references(read(step)),
                AssetUse("step", step.id, step.title, "documentation"),
            )
            note(
                asset_references(read_compiled(step)),
                AssetUse("step", step.id, step.title, "compiled docs"),
            )

        holders: list[NodeId] = [project.id, *(step.id for step in project.steps)]
        return [
            AssetLocation(
                node_id=node_id,
                module_id=MODULE_ID,
                name=name,
                uses=tuple(referenced.get(name, ())),
            )
            for node_id in holders
            for name in area_assets(files, node_id, MODULE_ID)
        ]

    return AssetSource(id=MODULE_ID, label="Documentation", scan=scan)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    return "documented" if read(step) else ""


# -- the compiled document ---------------------------------------------------------------------


def read_compiled(step: Step) -> str:
    return step.module_text.get(COMPILED_ID, "")


def read_stamp(step: Step) -> dict[str, Any]:
    """What the last compile recorded, or ``{}`` — a collector nobody has compiled yet.

    There is no ``{"on": true}`` marker here on purpose: a collector is already marked by
    ``step_feature`` or ``step_milestone``, and absence of this entry is the honest way to
    say *never compiled*.
    """
    entry = step.module_data.get(COMPILED_ID)
    return dict(entry) if isinstance(entry, dict) else {}


def read_digest(step: Step) -> str:
    """The digest of the sources the stored document was compiled from, or ""."""
    found = read_stamp(step).get("digest")
    return found if isinstance(found, str) else ""


def write_stamp(digest: str, at: float, provider: str, model: str, sources: int) -> dict[str, Any]:
    """What one compile recorded. ``at`` and ``sources`` are floats: a module that writes a
    number owes it one, or a file's bytes would depend on whether the project had been
    reopened (``FORMAT.md``)."""
    return stamped(
        {
            "digest": digest,
            "at": float(at),
            "provider": provider,
            "model": model,
            "sources": float(sources),
        },
        COMPILED_FORMAT.version,
    )


def compiled_summary(step: Step) -> str:
    return "compiled docs" if read_compiled(step) else ""


# Last, because they name the pieces above: the declarations everything else reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Docs",
    summary="What a step contributes to the product's documentation, in markdown.",
    data_format=DATA_FORMAT,
    phrase=summary,
)

COMPILED_SPEC = AspectSpec(
    id=COMPILED_ID,
    label="Compiled Docs",
    summary="The document a feature or milestone compiles from the documentation it gathers.",
    data_format=COMPILED_FORMAT,
    phrase=compiled_summary,
)
