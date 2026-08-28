"""Assembling the prompt an agent starts a step with.

The module never learns what the context sections *are* — a handoff, a global note — it is
handed finished :class:`PromptPart`s by the composition root, which is the one file allowed
to know every module's vocabulary. The project's standing instruction and the step's own are
this module's data, so they arrive as plain arguments. The same assembly answers the GUI's
Run Agent, the ``dplanner agent prompt`` verb, and the preview and fallback dialogs, so none
of them can drift.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from dplanner.domain.model import Product, Step
from dplanner.domain.store import FilesFor


@dataclass(frozen=True)
class PromptPart:
    """One block of context from elsewhere: who it is from, the text, the files it carries."""

    heading: str
    body: str
    files: tuple[str, ...] = ()


# (product, step, files) -> the blocks a briefing carries. The store's file lookup is the
# third argument so a block can name real asset paths.
PartsFor = Callable[[Product, Step, FilesFor], Sequence[PromptPart]]


def _no_parts(_product: Product, _step: Step, _files: FilesFor) -> Sequence[PromptPart]:
    return ()


@dataclass(frozen=True)
class Briefing:
    """The cross-module half of the prompt, assembled once by the composition root.

    One object in one vocabulary for both surfaces: the window's Deps and ``dplanner
    agent prompt`` used to declare these four members separately, in two different
    callable shapes, with two adapter closures in the root bridging them.

    ``parts`` is handed-forward context (a handoff, a global note); ``sections`` the
    step's own facts (description, requirements, the PR); ``epilogue`` closes the prompt
    with the report-back protocol and ``preamble`` opens it. The default is the honest
    empty briefing of a build where no other module contributes.
    """

    parts: PartsFor = _no_parts
    sections: PartsFor = _no_parts
    epilogue: Callable[[Step], str] = field(default=lambda _step: "")
    preamble: str = ""


EMPTY_BRIEFING = Briefing()


@dataclass(frozen=True)
class PromptSegment:
    """A stretch of the assembled text and where it came from.

    ``origin`` is one of ``header``, ``protocol`` (preamble and epilogue), ``project``,
    ``context``, ``instruction``, ``inherited``. Concatenating the segment texts
    reproduces ``AssembledPrompt.text`` exactly — a display that colours by origin can
    never show something other than what is sent.
    """

    origin: str
    text: str


@dataclass(frozen=True)
class AssembledPrompt:
    text: str
    files: tuple[str, ...]  # Every file the prompt references, in reading order.
    segments: tuple[PromptSegment, ...] = ()


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


def section_lines(section: PromptPart) -> list[str]:
    """A fact about the step itself as a first-class block — its description, its
    requirements — where ``part_lines`` frames context handed forward from elsewhere."""
    lines = [f"## {section.heading}", ""]
    if section.body:
        lines += [section.body.rstrip(), ""]
    lines += _files_lines(section.files)
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
    sections: Sequence[PromptPart] = (),
) -> AssembledPrompt:
    """The whole prompt as markdown, and the files it points at.

    ``preamble`` opens the briefing — preflight checks the agent must pass before touching
    the work, worded by the composition root like the epilogue is.
    ``project_instruction`` is the project's standing instruction, ahead of the step's own;
    either instruction's section disappears entirely when it is empty and carries no files,
    which is what lets a step ride on the standing instruction alone.
    ``sections`` are the step's own facts — a description, the requirements it implements —
    worded by the composition root and rendered here as opaque blocks, between the standing
    instruction and the step's, so the agent reads what the step *is* before how to do it.
    """
    blocks: list[tuple[str, list[str]]] = [
        ("header", [f"# Step: {step_title}", "", f"Project: {project_title}", ""])
    ]
    if preamble:
        blocks.append(("protocol", ["## Before you start", "", preamble.rstrip(), ""]))
    if project_instruction or project_files:
        project_lines = ["## Project instructions", ""]
        if project_instruction:
            project_lines += [project_instruction.rstrip(), ""]
        project_lines += _files_lines(project_files)
        blocks.append(("project", project_lines))
    if sections:
        blocks.append(
            ("context", [line for section in sections for line in section_lines(section)])
        )
    if instruction or instruction_files:
        instruction_lines = ["## Instructions", ""]
        if instruction:
            instruction_lines += [instruction.rstrip(), ""]
        instruction_lines += _files_lines(instruction_files)
        blocks.append(("instruction", instruction_lines))
    if parts:
        inherited_lines = ["## Context handed forward from earlier steps", ""]
        for part in parts:
            inherited_lines += part_lines(part)
        blocks.append(("inherited", inherited_lines))
    if epilogue:
        blocks.append(("protocol", ["## When you are done", "", epilogue.rstrip(), ""]))
    files = (
        *project_files,
        *(path for section in sections for path in section.files),
        *instruction_files,
        *(path for part in parts for path in part.files),
    )
    # Each segment carries the newline that joins it to the next, so the concatenation
    # is exactly the joined text — the invariant PromptSegment promises.
    segments = tuple(
        PromptSegment(
            origin, "\n".join(block) + ("\n" if index < len(blocks) - 1 else "")
        )
        for index, (origin, block) in enumerate(blocks)
    )
    text = "\n".join(line for _origin, block in blocks for line in block)
    return AssembledPrompt(text=text, files=files, segments=segments)
