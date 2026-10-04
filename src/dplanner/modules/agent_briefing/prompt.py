"""The prompt's shape: blocks, segments, and the one assembly that joins them.

:func:`assemble` renders blocks it does not understand — a note index, a topology — in a
fixed order, so the text an agent is launched with, the ``dplanner agent prompt`` verb and
the Agent tab's panes are one rendering. What goes *in* the blocks is the rest of this
package (:mod:`.compose`).

The hand-overs — :func:`conflict_prompt`, :func:`problems_prompt`, :func:`reconcile_prompt`
— are the briefings for a run that is not carrying out a step.
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
    the work, worded like the epilogue is (:mod:`.protocol`).
    ``project_instruction`` is the project's standing instruction, ahead of the step's own;
    either instruction's section disappears entirely when it is empty and carries no files,
    which is what lets a step ride on the standing instruction alone.
    ``sections`` are the step's own facts — a description, the feature it realises —
    worded in :mod:`.sections` and rendered here as opaque blocks, between the standing
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


def problems_prompt(
    project_title: str,
    plan_root: str,
    problems: Sequence[tuple[str, str, str]],
) -> str:
    """The briefing for an agent sent at what is wrong with a plan.

    ``problems`` is one ``(check, subject, message)`` per finding, exactly as
    ``dplanner project lint`` reports them — every message already names the verb that
    closes its gap, which is the whole reason this prompt can be short.

    The third hand-over, and the one with no step at all: no worktree, no briefing of a
    step's own, and a preamble written here rather than by the briefing, since that one is
    per step and says step-specific things. What it carries is the plan's own repository,
    the list, and the order to read the topology first — the verbs that reshape a graph are
    behind that gate, and an agent that has not been through it will be refused by the
    first one it tries.
    """
    preamble = ""
    if plan_root:
        preamble = (
            f"You are in the plan's own repository, `{plan_root}`. This run changes the"
            " **plan** and nothing else: do not edit code, and do not switch branches."
            " Never kill a process by name or pattern — other agents may be running with"
            " the same names."
        )
    lines = [
        "## What `dplanner project lint` reports",
        "",
        "Every line names the verb that closes it.",
        "",
    ]
    for check, subject, message in problems:
        lines.append(f"- **{subject}** — {message}  `[{check}]`")
    lines += [
        "",
        "## Instructions",
        "",
        f"Run `dplanner topology show '{project_title}'` first: it prints how this graph is"
        " meant to be shaped, and the verbs that reshape one are refused until you have."
        " Then close each finding above with the verb it names, asking the developer"
        " whenever a fix would change what the plan *means* rather than how it is"
        " recorded. A finding you decide to live with is one to say so about rather than"
        " silently leave.",
        "",
        "## When you are done",
        "",
        f"Run `dplanner project lint '{project_title}'` again and report what is left.",
    ]
    return handover_prompt(
        f"# Problems in the plan: {project_title}", project_title, preamble, "\n".join(lines)
    )


def reconcile_prompt(repo_root: str, branch: str) -> str:
    """The briefing for an agent sent to push a save the remote refused.

    DPlanner's save committed, then rebasing onto ``origin/<branch>`` conflicted and was
    aborted — so the checkout is clean, the commits are local, and what is left is exactly
    the rebase, done by somebody who can read both sides. A plan repository, not a step's:
    no project, no step and no preamble of the briefing's, since this run touches neither.
    """
    return "\n".join(
        [
            f"# Reconcile a plan repository with its remote: `{branch}`",
            "",
            "## What happened",
            "",
            f"You are in `{repo_root}`, a git repository holding DPlanner plans. A DPlanner"
            f" save committed locally, but `origin/{branch}` has commits that change the same"
            " lines, so rebasing onto it conflicted and was aborted. The working tree is as"
            " the save left it.",
            "",
            "## Instructions",
            "",
            f"1. `git fetch origin`, then `git rebase origin/{branch}`.",
            "2. Resolve each conflict so that nothing either side meant is lost. These are"
            " plan files: a `.json` entry is one module's structured data, a `.md` entry its"
            " prose, and `step.json` a step's title and links — keep every file valid JSON."
            " Where two versions cannot be reconciled, keep both and say so in the entry.",
            "3. `git add` what you resolved and `git rebase --continue` until it finishes.",
            f"4. `git push origin {branch}`. Never force-push.",
            "",
            "Change nothing outside the conflicts, do not switch branches, and never kill a"
            " process by name or pattern — other agents may be running with the same names."
            " If a conflict needs a judgement only the developer can make, stop and ask.",
            "",
            "## When you are done",
            "",
            "Report what each conflict was and how you settled it. The DPlanner window takes"
            " in the rewritten files by itself.",
            "",
        ]
    )


def listed(words: Sequence[str]) -> str:
    """``A``, ``A and B``, ``A, B and C`` — a list as a sentence says it."""
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + f" and {words[-1]}"


def quoted(key: str) -> str:
    """A step's key or title as a verb takes it: quoted only when it has a space."""
    return f"'{key}'" if " " in key else key
