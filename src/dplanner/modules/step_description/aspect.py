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

from dplanner.core.module_data import ModuleDataFormat
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

MODULE_ID = "step_description"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

SPEC = AspectSpec(
    id=MODULE_ID,
    label="Description",
    summary="What a step actually is, in markdown, with any images it references.",
    data_format=DATA_FORMAT,
)


def read(step: Step) -> str:
    return step.module_text.get(MODULE_ID, "")


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
