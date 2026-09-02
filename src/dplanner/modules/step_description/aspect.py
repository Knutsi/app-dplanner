"""The description aspect: prose in ``module_text``, images in a module file area.

Two stores, because the two kinds of content want opposite things:

**The markdown is model state.** It lives in ``step.module_text[MODULE_ID]`` and is written
as ``modules/step_description.md``, so it diffs line by line, is edited through the shared
text stack — positional splicing, undo coalescing, origin-based echo suppression — and can
be undone in a window that is open while the CLI writes it. Keeping it inside a JSON entry
would have turned every prose edit into one escaped-newline line, and cost the text stack.

**The images are not.** They are opaque bytes nobody merges, so they live in the module's
file area, ``modules/step_description/assets/``, reached through ``store.files()`` and the
content-addressed helpers in :mod:`dplanner.domain.assets` — which also carries the
reasoning for why an asset add is not undoable.
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
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.store import FilesFor

MODULE_ID = "step_description"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)


def read(step: Step) -> str:
    return step.module_text.get(MODULE_ID, "")


def enabled(step: Step) -> bool:
    """Whether this step carries a description — the Type toggle's answer.

    **Absence means on**, the opposite of a ticket or a check, because a description is
    what a step ordinarily *is*: every step wants one, and the ones that do not — a
    milestone, which is a marker in the graph rather than work — are the exception worth
    recording. So the stored entry is the opt-out, existing projects change not at all, and
    ``FORMAT.md``'s "absence encodes the default" holds with the default being yes.
    """
    entry = step.module_data.get(MODULE_ID)
    return not (entry and entry.get("off"))


def write_state(on: bool) -> dict[str, Any]:
    """The opt-out entry. On gives ``{}``, which removes the file and restores the default.

    The prose lives in ``module_text`` and is cleared alongside this, in one command — the
    shape ``step_agent_instruction`` established, so one Ctrl+Z restores both.
    """
    return {} if on else stamped({"off": True}, DATA_FORMAT.version)


def asset_source() -> AssetSource:
    """This aspect's slice of the project's asset catalog.

    A description image is used while the markdown links to it — the same claim the
    ``description.image-missing`` lint makes in the opposite direction.
    """

    def scan(
        _library: Library, project: Project, files: FilesFor
    ) -> Sequence[AssetLocation]:
        locations: list[AssetLocation] = []
        for step in project.steps:
            names = area_assets(files, step.id, MODULE_ID)
            if not names:
                continue
            referenced = set(asset_references(read(step)))
            locations += [
                AssetLocation(
                    node_id=step.id,
                    module_id=MODULE_ID,
                    name=name,
                    uses=(AssetUse("step", step.id, step.title, "description"),)
                    if name in referenced
                    else (),
                )
                for name in names
            ]
        return locations

    return AssetSource(id=MODULE_ID, label="Descriptions", scan=scan)


def summary(step: Step) -> str:
    """The first line of real prose, for a step's second line in a list.

    Headings are skipped rather than shown: a description almost always opens with the
    step's own title, and repeating it beside the title says nothing.
    """
    body = read(step)
    if not body:
        return ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:60]
    return "described"


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Description",
    summary="What a step actually is, in markdown, with any images it references.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
