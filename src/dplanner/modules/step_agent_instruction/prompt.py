"""Assembling the prompt an agent starts a step with.

The module never learns what the context sections *are* — a handoff, a global note — it is
handed finished :class:`PromptPart`s by the composition root, which is the one file allowed
to know every module's vocabulary. The same assembly answers the GUI's Run Agent, the
``dplanner agent prompt`` verb, and the fallback dialog, so the three can never drift.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptPart:
    """One block of context from elsewhere: who it is from, the text, the files it carries."""

    heading: str
    body: str
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssembledPrompt:
    text: str
    files: tuple[str, ...]  # Every file the prompt references, in reading order.


def assemble(
    step_title: str,
    project_title: str,
    instruction: str,
    parts: Sequence[PromptPart],
    epilogue: str,
    preamble: str = "",
) -> AssembledPrompt:
    """The whole prompt as markdown, and the files it points at.

    ``preamble`` opens the briefing — preflight checks the agent must pass before touching
    the work, worded by the composition root like the epilogue is.
    """
    lines = [f"# Step: {step_title}", "", f"Project: {project_title}", ""]
    if preamble:
        lines += ["## Before you start", "", preamble.rstrip(), ""]
    lines += ["## Instructions", "", instruction.rstrip(), ""]
    if parts:
        lines += ["## Context handed forward from earlier steps", ""]
        for part in parts:
            lines += [f'### From "{part.heading}"', ""]
            if part.body:
                lines += [part.body.rstrip(), ""]
            if part.files:
                lines += ["Files:", *[f"- {path}" for path in part.files], ""]
    if epilogue:
        lines += ["## When you are done", "", epilogue.rstrip(), ""]
    files = tuple(path for part in parts for path in part.files)
    return AssembledPrompt(text="\n".join(lines), files=files)
