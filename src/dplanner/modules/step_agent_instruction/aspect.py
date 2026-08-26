"""The agent-instruction aspect: prose written for whoever implements the step, not for a
person deciding whether to.

A sibling of the description rather than a replacement for it, and the distinction is the
point. A description says what the step *is* — it is read by anyone planning the work. An
instruction says how to carry it out in this codebase: which files, which convention, what
"done" has to satisfy. Keeping them apart means a plan stays readable to people while still
carrying everything an agent needs, instead of one field trying to be both.

Prose, so it lives in ``module_text`` and diffs line by line. There are no images and no file
area: an instruction that needs a diagram is describing the work, not directing it.
"""

from dplanner.core.module_data import ModuleDataFormat
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Step

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


def summary(step: Step) -> str:
    """One short phrase for a step's row — how much direction there is, not what it says.

    The text itself is instructions to a machine and rarely reads well out of context, so a
    row says that it exists and how much of it there is.
    """
    body = read(step)
    if not body:
        return ""
    return "instructed" if len(body) < 200 else f"instructed ({len(body)} chars)"
