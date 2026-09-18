"""The agent aspect: marks a step for agent execution, and carries how to carry it out.

**The description is the instructions.** A step marked for an agent is briefed with its
own description — one text, written once, read by people and machines alike. This aspect
adds the mark itself (``module_data``: the step is an agent step) and, only where
how-to-execute genuinely differs from what-it-is, a *separate* instruction (prose in
``module_text``). Writing a separate instruction implies the mark, which is also what
keeps plans from before the mark existed working unchanged.

Prose, so the separate instruction lives in ``module_text`` and diffs line by line. It may
carry images in its file area — a mockup, an annotated screenshot — handed to the agent
beside the prompt at launch.

**Where the agent works is the step's decision, not a setting.** The entry's ``worktree``
says whether Run Agent puts the agent in a fresh git worktree on its own branch — absent
means *on*, and ``false`` is the opt-out — because whether a step can share the checkout
the window shows is a fact about that step (a merge, a release cut, a conflict to settle),
not about the machine. A global switch was where this lived first, and one switch for
every step is a switch nobody dares turn off.

The namespace spans node kinds (FORMAT.md's rule, like ``estimation``): beside a step it is
that step's separate instruction; beside the *project* it is the project's standing
instruction, prepended to every step's briefing. The id keeps its historical ``step_``
prefix — renaming a module is a Takeover that churns every workspace, and the prefix only
names where the aspect began.
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
    assets,
)
from dplanner.domain.model import Library, NodeId, Project, Step
from dplanner.domain.store import FilesFor

MODULE_ID = "step_agent_instruction"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)


def read(step: Step) -> str:
    """The step's *separate* instruction — empty for most agent steps, whose briefing
    carries the description instead."""
    return step.module_text.get(MODULE_ID, "")


def enabled(step: Step) -> bool:
    """Whether this is an agent step. The stored mark says so; a separate instruction
    implies it, so a plan written before the mark existed still reads as agent work."""
    return bool(step.module_data.get(MODULE_ID)) or bool(read(step))


def separate_instruction(step: Step) -> bool:
    """Whether the step opted into an instruction distinct from its description.

    Stored rather than derived, because "opted in but not yet typed" is a real state that
    must survive a selection change. Text-presence still implies it — the two encodings
    cannot disagree because turning the aspect off clears both.
    """
    entry = step.module_data.get(MODULE_ID) or {}
    return bool(entry.get("separate")) or bool(read(step))


def uses_worktree(step: Step) -> bool:
    """Whether Run Agent puts this step's agent in a fresh worktree. Absence means yes."""
    entry = step.module_data.get(MODULE_ID) or {}
    return entry.get("worktree", True) is not False


def workplace(step: Step) -> str:
    """Which of the project's code locations this step's agent works in, by the row's
    id; "" means the primary — the project's first code row. A fact about the step, as
    the worktree choice is: two code repositories in a project means some steps are in
    one and some in the other."""
    entry = step.module_data.get(MODULE_ID) or {}
    found = entry.get("workplace", "")
    return found if isinstance(found, str) else ""


def write_state(
    on: bool, separate: bool = False, worktree: bool = True, workplace: str = ""
) -> dict[str, Any]:
    """The aspect's entry: ``{}`` when off (the file disappears), the mark otherwise.

    Only the opt-outs are written — ``separate`` when true, ``worktree`` when false, a
    ``workplace`` that is not the primary — so a plain agent step's entry stays the bare
    mark it always was.
    """
    if not on:
        return {}
    entry: dict[str, Any] = {"on": True}
    if separate:
        entry["separate"] = True
    if not worktree:
        entry["worktree"] = False
    if workplace:
        entry["workplace"] = workplace
    return stamped(entry, DATA_FORMAT.version)


def with_worktree(step: Step, worktree: bool) -> dict[str, Any]:
    """The step's entry with only its worktree choice changed — the mark, a stored
    ``separate`` flag and the workplace ride along, so flipping one field never loses
    another."""
    entry = step.module_data.get(MODULE_ID) or {}
    return write_state(
        True, separate=bool(entry.get("separate")), worktree=worktree, workplace=workplace(step)
    )


def with_workplace(step: Step, location_id: str) -> dict[str, Any]:
    """The step's entry with only its workplace changed; "" returns it to the primary."""
    entry = step.module_data.get(MODULE_ID) or {}
    return write_state(
        True,
        separate=bool(entry.get("separate")),
        worktree=uses_worktree(step),
        workplace=location_id,
    )


def read_project(project: Project) -> str:
    """The project's standing instruction — the part of every briefing that is the same."""
    return project.module_text.get(MODULE_ID, "")


def asset_paths(files: FilesFor, node_id: NodeId) -> tuple[str, ...]:
    """A node's instruction files as absolute paths.

    Absolute because one library spans several project directories: a relative path would
    need to say which root it is relative to, and the agent runs in the repository, not in
    any store root, so the prompt needs the absolute form anyway.

    A node the store has never flushed has no directory yet, and the store says so with a
    ``KeyError`` — a node created this run simply has no files to list.
    """
    try:
        area = files(node_id, MODULE_ID)
    except KeyError:
        return ()
    return tuple(str(area.absolute(name)) for name in assets(area))


def asset_source() -> AssetSource:
    """This aspect's slice of the project's asset catalog.

    Every file here is used, whether or not the prose links it: the briefing hands the
    whole area to the agent (``_briefing_instruction``: the files "always ride with the
    block — they were attached to it"), so an unreferenced file is still payload, never
    litter. Removing one from a briefing is the instruction editor's gesture, not a
    sweep's.
    """

    def scan(_library: Library, project: Project, files: FilesFor) -> Sequence[AssetLocation]:
        def held(node_id: NodeId, subject: str, kind: str, where: str) -> list[AssetLocation]:
            return [
                AssetLocation(
                    node_id=node_id,
                    module_id=MODULE_ID,
                    name=name,
                    uses=(AssetUse(kind, node_id, subject, where),),
                )
                for name in area_assets(files, node_id, MODULE_ID)
            ]

        locations = held(project.id, project.title, "project", "standing instruction")
        for step in project.steps:
            locations += held(step.id, step.title, "step", "agent instruction")
        return locations

    return AssetSource(id=MODULE_ID, label="Agent instructions", scan=scan)


def summary(step: Step) -> str:
    """One short phrase for a step's row — that an agent will do it, and how much extra
    direction there is. The text itself is instructions to a machine and rarely reads well
    out of context."""
    body = read(step)
    if body:
        return "instructed" if len(body) < 200 else f"instructed ({len(body)} chars)"
    return "agent" if enabled(step) else ""


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Agent",
    summary="Marks a step for agent execution. The description is the briefing's"
    " instructions unless a separate instruction is written.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
