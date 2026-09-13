"""Assembling the prompt an agent starts a step with.

The module never learns what the context sections *are* — a note index, a topology — it is
handed finished :class:`PromptPart`s by the composition root, which is the one file allowed
to know every module's vocabulary. The project's standing instruction and the step's own are
this module's data, so they arrive as plain arguments. The same assembly answers the GUI's
Run Agent, the ``dplanner agent prompt`` verb, and the preview and fallback dialogs, so none
of them can drift.

:func:`conflict_prompt` is the one other prompt this module launches: the briefing for an
agent asked to reconcile an entry the window and another writer both changed.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from dplanner.domain.model import Library, Step
from dplanner.domain.repositories import RepositoryFacts
from dplanner.domain.store import FilesFor
from dplanner.modules.step_agent_instruction.aspect import asset_paths, read


@dataclass(frozen=True)
class PromptPart:
    """One block of context from elsewhere: who it is from, the text, the files it carries."""

    heading: str
    body: str
    files: tuple[str, ...] = ()


# (library, step, files) -> the blocks a briefing carries. The store's file lookup is the
# third argument so a block can name real asset paths.
PartsFor = Callable[[Library, Step, FilesFor], Sequence[PromptPart]]


def _no_parts(_product: Library, _step: Step, _files: FilesFor) -> Sequence[PromptPart]:
    return ()


def _own_instruction(_product: Library, step: Step, files: FilesFor) -> PromptPart:
    """The module's own answer: the step's separate instruction and its images. The
    composition root swaps in the description when there is no separate one — a decision
    that crosses modules and so cannot be made here."""
    return PromptPart(heading="Instructions", body=read(step), files=asset_paths(files, step.id))


@dataclass(frozen=True)
class Briefing:
    """The cross-module half of the prompt, assembled once by the composition root.

    One object in one vocabulary for both surfaces: the window's Deps and ``dplanner
    agent prompt`` used to declare these four members separately, in two different
    callable shapes, with two adapter closures in the root bridging them.

    ``parts`` is what the project recorded for whoever works this step (the notes
    addressed to it, the index of the rest), rendered after the instructions;
    ``sections`` the step's own facts (description, the feature it realises, the PR);
    ``project_sections`` the project's — its topology — rendered beside the standing
    instruction; ``instruction`` the block the ``## Instructions`` heading carries — the
    step's separate instruction when one exists, the description otherwise, decided by
    the root; ``epilogue`` closes the prompt with the report-back protocol (handed the
    library, since the verbs it names address the project as well as the step) and
    ``preamble`` opens it — per step, told whether *this run* gets a worktree, since
    the preflight names the worktree the launcher prepares and a conflict run never has
    one whatever the step says, and handed the project's repository facts so it can say
    where the plan lives (None when the caller has none to give). The default is the
    honest empty briefing of a build where no other module contributes.
    """

    parts: PartsFor = _no_parts
    sections: PartsFor = _no_parts
    project_sections: PartsFor = _no_parts
    epilogue: Callable[[Library, Step], str] = field(default=lambda _library, _step: "")
    preamble: Callable[[Step, bool, RepositoryFacts | None], str] = field(
        default=lambda _step, _worktree, _facts: ""
    )
    instruction: Callable[[Library, Step, FilesFor], PromptPart] = _own_instruction


EMPTY_BRIEFING = Briefing()


@dataclass(frozen=True)
class PromptSegment:
    """A stretch of the assembled text, where it came from and what it is called.

    ``origin`` is one of ``header``, ``protocol`` (preamble and epilogue), ``project``,
    ``context``, ``instruction``, ``inherited`` (the parts after the instructions), and is
    what a display tints by. ``heading`` is the block's own markdown heading without the
    hashes, because an origin alone cannot tell *Before you start* from *When you are done*,
    nor one note block from the other — and "which block is this briefing's weight in?" is a
    question somebody has to be able to ask (``agent prompt --json``).

    There is one segment per block, so every block's size has a name. Concatenating the
    segment texts reproduces ``AssembledPrompt.text`` exactly — a display that colours by
    origin can never show something other than what is sent.
    """

    origin: str
    text: str
    heading: str = ""


@dataclass(frozen=True)
class AssembledPrompt:
    text: str
    files: tuple[str, ...]  # Every file the prompt references, in reading order.
    segments: tuple[PromptSegment, ...] = ()


def _files_lines(files: Sequence[str]) -> list[str]:
    if not files:
        return []
    return ["Files:", *[f"- {path}" for path in files], ""]


def section_lines(section: PromptPart) -> list[str]:
    """One block as markdown — a fact about the step, a project section, a part handed in
    after the instructions. Also how the Agent tab renders its Context and Inherited
    panes, so a pane and the prompt cannot describe the same block two ways."""
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
    project_sections: Sequence[PromptPart] = (),
) -> AssembledPrompt:
    """The whole prompt as markdown, and the files it points at.

    ``preamble`` opens the briefing — preflight checks the agent must pass before touching
    the work, worded by the composition root like the epilogue is.
    ``project_instruction`` is the project's standing instruction, ahead of the step's own;
    either instruction's section disappears entirely when it is empty and carries no files,
    which is what lets a step ride on the standing instruction alone.
    ``sections`` are the step's own facts — a description, the feature it realises —
    worded by the composition root and rendered here as opaque blocks, between the standing
    instruction and the step's, so the agent reads what the step *is* before how to do it.
    ``project_sections`` are the project's own facts — its topology — rendered right after
    the standing instruction, because they frame every step the same way. ``parts`` come
    after the instructions: what the project recorded for this step's worker, read once
    the work is understood.
    """
    blocks: list[tuple[str, str, list[str]]] = [
        ("header", "Step", [f"# Step: {step_title}", "", f"Project: {project_title}", ""])
    ]
    if preamble:
        blocks.append(
            ("protocol", "Before you start", ["## Before you start", "", preamble.rstrip(), ""])
        )
    if project_instruction or project_files:
        project_lines = ["## Project instructions", ""]
        if project_instruction:
            project_lines += [project_instruction.rstrip(), ""]
        project_lines += _files_lines(project_files)
        blocks.append(("project", "Project instructions", project_lines))
    # One block per section and per part, so each one's size has a name of its own.
    blocks += [("project", s.heading, section_lines(s)) for s in project_sections]
    blocks += [("context", s.heading, section_lines(s)) for s in sections]
    if instruction or instruction_files:
        instruction_lines = ["## Instructions", ""]
        if instruction:
            instruction_lines += [instruction.rstrip(), ""]
        instruction_lines += _files_lines(instruction_files)
        blocks.append(("instruction", "Instructions", instruction_lines))
    blocks += [("inherited", part.heading, section_lines(part)) for part in parts]
    if epilogue:
        blocks.append(
            ("protocol", "When you are done", ["## When you are done", "", epilogue.rstrip(), ""])
        )
    files = (
        *project_files,
        *(path for section in project_sections for path in section.files),
        *(path for section in sections for path in section.files),
        *instruction_files,
        *(path for part in parts for path in part.files),
    )
    # Each segment carries the newline that joins it to the next, so the concatenation
    # is exactly the joined text — the invariant PromptSegment promises.
    segments = tuple(
        PromptSegment(
            origin,
            "\n".join(block) + ("\n" if index < len(blocks) - 1 else ""),
            heading,
        )
        for index, (origin, heading, block) in enumerate(blocks)
    )
    text = "\n".join(line for _origin, _heading, block in blocks for line in block)
    return AssembledPrompt(text=text, files=files, segments=segments)


def handover_prompt(heading: str, project_title: str, preamble: str, body: str) -> str:
    """A briefing for a run that is not carrying out the step: the header, this module's
    own preflight, then whatever the asking module wrote.

    The two hand-overs — reconciling a conflict, compiling a collector's documentation —
    differ only in ``body``, and the body is the asking module's vocabulary: what "compile"
    means and which verb finishes it belong to the docs module, not here. So this wraps
    rather than composes, and the preamble is the one thing every run gets whatever it was
    opened for.
    """
    lines = [heading, f"Project: {project_title}", ""]
    if preamble:
        lines += ["## Before you start", "", preamble, ""]
    lines += [body.strip(), ""]
    return "\n".join(lines)


def conflict_prompt(
    step_title: str,
    project_title: str,
    preamble: str,
    entries: Sequence[tuple[str, str]],
) -> str:
    """The briefing for reconciling entries two writers changed at once.

    ``entries`` pairs each plan file (project-relative) with where the window's version of
    it was saved. The plan on disk holds the other writer's version — the window has yielded
    to it by the time the agent reads this — so the agent reads both, merges, and writes the
    result back with the verb that owns the entry. No status change and no handoff: this run
    does not carry out the step, it settles what two writers meant.
    """
    lines = [
        "## What happened",
        "",
        "The DPlanner window and a `dplanner` run changed the same entries of this plan"
        " within seconds of each other. The plan on disk now holds the run's version of"
        " each; the window's unsaved version was saved beside this prompt:",
        "",
    ]
    for path, mine in entries:
        lines.append(f"- `{path}` — the window's version: `{mine}`")
    lines += [
        "",
        "## Instructions",
        "",
        "For each entry, read both versions and merge them so that nothing either writer"
        " meant is lost. Write the result into the plan with the `dplanner` verb that owns"
        " the entry (`dplanner describe set --file …` for a description, `dplanner estimate"
        " set` for an estimate, `dplanner status set` for a status, and so on — `dplanner"
        " skill status` lists them). A `.json` entry is one module's structured data; a"
        " `.md` entry is its prose; `step.json` holds the step's title and links. If two"
        " versions cannot be reconciled, keep both in the entry and say so in it.",
        "",
        "## When you are done",
        "",
        f"Run `dplanner agent-state clear '{step_title}'` so the window stops showing this"
        " run as live. Do not change the step's status.",
    ]
    return handover_prompt(
        f"# Conflict on step: {step_title}", project_title, preamble, "\n".join(lines)
    )
