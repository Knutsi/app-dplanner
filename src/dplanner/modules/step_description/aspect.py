"""The description aspect: prose in ``module_text``, images in a module file area.

Two stores, because the two kinds of content want opposite things:

**The markdown is model state.** It lives in ``step.module_text[MODULE_ID]`` and is written
as ``modules/step_description.md``, so it diffs line by line, is edited through the shared
text stack — positional splicing, undo coalescing, origin-based echo suppression — and can
be undone in a window that is open while the CLI writes it. Keeping it inside a JSON entry
would have turned every prose edit into one escaped-newline line, and cost the text stack.

**The images are not.** They are opaque bytes nobody merges, so they live in the module's
file area, ``modules/step_description/assets/``, reached through ``store.files()``. They are
named by the hash of their content, which means attaching the same image twice is a no-op
and a link in the markdown never has to change.

An asset add is not undoable, and that is the honest trade: undoing a paste would leave the
markdown pointing at a file that had gone. An orphaned blob is recoverable; a dangling link
is not.
"""

import hashlib
from pathlib import PurePosixPath

from dplanner.core.module_data import ModuleDataFormat
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step
from dplanner.domain.store import ModuleFileArea

MODULE_ID = "step_description"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

ASSETS_DIR = "assets"

SPEC = AspectSpec(
    id=MODULE_ID,
    label="Description",
    summary="What a step actually is, in markdown, with any images it references.",
    data_format=DATA_FORMAT,
)


def read(step: Step) -> str:
    return step.module_text.get(MODULE_ID, "")


def asset_name(data: bytes, filename: str) -> str:
    """``assets/<hash><suffix>`` — the path to reference from the markdown.

    Content-addressed so the same image attached twice is one file, and so a rename upstream
    never churns a link. The suffix is kept because a browser and a person both use it to
    tell what the file is.
    """
    suffix = PurePosixPath(filename).suffix.lower()
    return f"{ASSETS_DIR}/{hashlib.sha256(data).hexdigest()[:16]}{suffix}"


def attach(area: ModuleFileArea, data: bytes, filename: str) -> str:
    """Put an image in the step's file area; returns the path to link to."""
    name = asset_name(data, filename)
    area.write_bytes(name, data)
    return name


def assets(area: ModuleFileArea) -> list[str]:
    return sorted(f"{ASSETS_DIR}/{name}" for name in area.names(ASSETS_DIR))


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
