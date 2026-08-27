"""The agent-instruction aspect: prose written for whoever implements the step, not for a
person deciding whether to.

A sibling of the description rather than a replacement for it, and the distinction is the
point. A description says what the step *is* — it is read by anyone planning the work. An
instruction says how to carry it out in this codebase: which files, which convention, what
"done" has to satisfy. Keeping them apart means a plan stays readable to people while still
carrying everything an agent needs, instead of one field trying to be both.

Prose, so it lives in ``module_text`` and diffs line by line. An instruction may carry
images in its file area — a mockup, an annotated screenshot — handed to the agent beside
the prompt at launch.

The namespace spans node kinds (FORMAT.md's rule, like ``estimation``): beside a step it is
that step's instruction; beside the *project* it is the project's standing instruction,
prepended to every step's briefing. The id keeps its historical ``step_`` prefix — renaming
a module is a Takeover that churns every workspace, and the prefix only names where the
aspect began.
"""

from collections.abc import Callable

from dplanner.core.module_data import ModuleDataFormat
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.assets import assets
from dplanner.domain.model import NodeId, Project, Step
from dplanner.domain.store import ModuleFileArea

MODULE_ID = "step_agent_instruction"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

SPEC = AspectSpec(
    id=MODULE_ID,
    label="Agent",
    summary="How a coding agent should carry this step out, in markdown.",
    data_format=DATA_FORMAT,
)


def read(step: Step) -> str:
    return step.module_text.get(MODULE_ID, "")


def read_project(project: Project) -> str:
    """The project's standing instruction — the part of every briefing that is the same."""
    return project.module_text.get(MODULE_ID, "")


def asset_paths(
    files: Callable[[NodeId, str], ModuleFileArea], node_id: NodeId
) -> tuple[str, ...]:
    """A node's instruction files as workspace-relative paths.

    A node the store has never flushed has no directory yet, and the store says so with a
    ``KeyError`` — a node created this run simply has no files to list.
    """
    try:
        area = files(node_id, MODULE_ID)
    except KeyError:
        return ()
    return tuple(f"{area.directory}/{name}" for name in assets(area))


def summary(step: Step) -> str:
    """One short phrase for a step's row — how much direction there is, not what it says.

    The text itself is instructions to a machine and rarely reads well out of context, so a
    row says that it exists and how much of it there is.
    """
    body = read(step)
    if not body:
        return ""
    return "instructed" if len(body) < 200 else f"instructed ({len(body)} chars)"
