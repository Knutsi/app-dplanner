"""Assembling the prompt an agent starts a step with.

The module never learns what the context sections *are* — a handoff, a global note — it is
handed finished :class:`PromptPart`s by the composition root, which is the one file allowed
to know every module's vocabulary. The project's standing instruction and the step's own are
this module's data, so they arrive as plain arguments. The same assembly answers the GUI's
Run Agent, the ``dplanner agent prompt`` verb, and the preview and fallback dialogs, so none
of them can drift.
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


def _files_lines(files: Sequence[str]) -> list[str]:
    if not files:
        return []
    return ["Files:", *[f"- {path}" for path in files], ""]


def part_lines(part: PromptPart) -> list[str]:
    """One context block as markdown — also how the Agent tab renders its Inherited pane,
    so the pane and the prompt cannot describe the same context two ways."""
    lines = [f'### From "{part.heading}"', ""]
    if part.body:
        lines += [part.body.rstrip(), ""]
    lines += _files_lines(part.files)
    return lines


def assemble(
    step_title: str,
    project_title: str,
    instruction: str,
    parts: Sequence[PromptPart],
    epilogue: str,
    preamble: str = "",
    project_instruction: str = "",
    project_files: Sequence[str] = (),
    instruction_files: Sequence[str] = (),
) -> AssembledPrompt:
    """The whole prompt as markdown, and the files it points at.

    ``preamble`` opens the briefing — preflight checks the agent must pass before touching
    the work, worded by the composition root like the epilogue is.
    ``project_instruction`` is the project's standing instruction, ahead of the step's own;
    either instruction's section disappears entirely when it is empty and carries no files,
    which is what lets a step ride on the standing instruction alone.
    """
    lines = [f"# Step: {step_title}", "", f"Project: {project_title}", ""]
    if preamble:
        lines += ["## Before you start", "", preamble.rstrip(), ""]
    if project_instruction or project_files:
        lines += ["## Project instructions", ""]
        if project_instruction:
            lines += [project_instruction.rstrip(), ""]
        lines += _files_lines(project_files)
    if instruction or instruction_files:
        lines += ["## Instructions", ""]
        if instruction:
            lines += [instruction.rstrip(), ""]
        lines += _files_lines(instruction_files)
    if parts:
        lines += ["## Context handed forward from earlier steps", ""]
        for part in parts:
            lines += part_lines(part)
    if epilogue:
        lines += ["## When you are done", "", epilogue.rstrip(), ""]
    files = (
        *project_files,
        *instruction_files,
        *(path for part in parts for path in part.files),
    )
    return AssembledPrompt(text="\n".join(lines), files=files)
