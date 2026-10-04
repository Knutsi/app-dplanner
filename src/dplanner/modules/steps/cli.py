"""``dplanner step …`` — a project's graph, one step at a time, from a terminal.

Every verb builds the same command from ``domain/commands.py`` that the menu does, so an
edit made here is undoable in a window open on the same library. ``step duplicate`` is the
canvas's Duplicate, handed in by the root as one function, because the clipboard that clones
a step is the canvas's own.

A package with no ``module.py``: the whole of it is the surface another module may import,
which is how ``project show`` prints the rows ``step list`` does (:func:`step_row`).

Qt-free by rule — see ``tests/test_architecture.py``.
"""

import json
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import (
    find_project,
    find_step,
    project_arg,
    project_of,
    project_of_step,
    project_of_steps,
    step_arg,
)
from dplanner.domain.commands import (
    AddNodeCommand,
    Command,
    SetEdgesCommand,
    SetFieldCommand,
    redirect_edges_command,
    remove_edges_command,
    remove_steps_command,
)
from dplanner.domain.model import (
    EDGE_KINDS,
    SOURCE,
    WAITER,
    EdgeEnd,
    Library,
    Project,
    Step,
    StepId,
)
from dplanner.domain.ordering import ports
from dplanner.domain.store import FilesFor

# How a verb here removes steps: the domain's plain removal unless the root hands over one
# that knows more — a stack closing its chain round a member that goes.
type RemoveSteps = Callable[[Library, Sequence[StepId], str], Command]


# How ``step duplicate`` copies steps into a project: applies the clone and writes the
# copies' files, answering the copies in the originals' order — the canvas's, from the root.
type Duplicate = Callable[[CliContext, Sequence[StepId], Project], list[Step]]


def _plain(_waiter: Step, _source: Step) -> bool:
    return False


def _no_key(_step: Step) -> str:
    return ""


def _no_branches(_project: Project) -> Mapping[StepId, str]:
    return {}


def lint_checks() -> list[LintCheck]:
    def dangling_requires(
        _product: Library, project: Project, _files: FilesFor
    ) -> list[LintFinding]:
        # Every verb that deletes a step takes the links into it along, so a ghost id is
        # what an edit outside the window or a merge left; requires()/depths() silently
        # skip it, and this is the one reader that says it is there.
        ids = {step.id for step in project.steps}
        return [
            LintFinding(
                check="graph.requires-dangling",
                subject_id=step.id,
                subject=step.title,
                message=f"waits on {target[:8]}, a step that no longer exists — left by an "
                "edit outside the window or a merge; take the id out of its step.json, "
                "or ignore",
            )
            for step in project.steps
            for target in step.edges.get("requires", [])
            if target not in ids
        ]

    def orphan(_product: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        # The canvas already rings one in the refusal red — the one mark that says
        # *something is wrong here* rather than *this is where the graph ends*. This is the
        # same derivation, read by the terminal. A lone step is nobody's orphan.
        if len(project.steps) < 2:
            return []
        connected = ports(project.steps)
        return [
            LintFinding(
                check="graph.orphan",
                subject_id=step.id,
                subject=step.title,
                message="is on no graph — nothing waits on it and it waits on nothing; "
                f"link it with `dplanner step link '{step.title}' <step>`, or remove it",
            )
            for step in project.steps
            if connected[step.id] == (False, False)
        ]

    return [dangling_requires, orphan]


def commands(
    step_authors: Sequence[StepAuthor] = (),
    key_of: Callable[[Step], str] = _no_key,
    *,
    auto_progresses: Callable[[Step, Step], bool] = _plain,
    branches_in: Callable[[Project], Mapping[StepId, str]] = _no_branches,
    remove_steps: RemoveSteps = remove_steps_command,
    duplicate: Duplicate,
) -> list[CliCommand]:
    """``step_authors`` let ``step add`` author the step in the same call, in report order.
    ``key_of`` is the step's readable key (``S7``, ``F3``) — the letter is a fact about
    aspects this file never reads, so the root hands the rule in and every row prints the
    same key the canvas paints; ``auto_progresses`` marks, in ``step show``, a link its
    waiter may start across from review on; ``branches_in`` names the feature branch each
    step's work is on. ``remove_steps`` is how ``step remove`` builds its removal — the
    graph editor's, which closes a stack round a member that goes — and ``duplicate`` is
    the canvas's Duplicate (:func:`~dplanner.modules.canvas.cli.duplicator`)."""

    def _configure_step_add(parser: ArgumentParser) -> None:
        project_arg(parser)
        parser.add_argument("title", help="what the step is called")
        parser.add_argument(
            "--after",
            action="append",
            default=[],
            metavar="STEP",
            help="a step this one waits on; repeatable",
        )
        for author in step_authors:
            author.configure(parser)

    def _step_add(context: CliContext, args: Namespace) -> int:
        if sum(1 for author in step_authors if author.reads_stdin(args)) > 1:
            raise CliError("only one flag may read stdin (-) per call")
        library = context.library
        project = find_project(library, args.project)
        step = Step(title=args.title)
        context.apply(AddNodeCommand(project.id, step))
        waiting = [find_step(library, needle).id for needle in args.after]
        if waiting:
            context.apply(SetEdgesCommand(step.id, "requires", waiting))
        # Composition-root order is report order. No rollback: an author that raises
        # aborts the run, and the transaction writes nothing — the step included.
        data, notes = step_row(library, step, key_of), []
        for author in step_authors:
            contributed = author.author(context, step, args)
            if contributed is not None:
                data |= contributed.data
                notes.append(f"  {contributed.note}")
        context.report(
            data,
            "\n".join(
                [f"Added {key_of(step)} {step.title!r} to {project.title}  {step.id}", *notes]
            ),
        )
        return 0

    def _configure_duplicate(parser: ArgumentParser) -> None:
        parser.add_argument(
            "step", nargs="+", help="steps to copy: id, folder name, or part of a title"
        )
        parser.add_argument(
            "--into",
            metavar="PROJECT",
            help="the project the copies go into; default: the steps' own",
        )

    def _project_of_duplicate(context: CliContext, args: Namespace) -> Project:
        """The project the copies land in — what the topology gate asks about."""
        library = context.library
        if args.into:
            return find_project(library, args.into)
        return library.project_of(find_step(library, args.step[0], context.current).id)

    def _step_duplicate(context: CliContext, args: Namespace) -> int:
        """The window's Duplicate, as one transaction: the same clone command, the same
        policies, the attachments copied after it."""
        library = context.library
        originals = [find_step(library, needle, context.current) for needle in args.step]
        target = _project_of_duplicate(context, args)
        copies = duplicate(context, [s.id for s in originals], target)
        pairs = list(zip(originals, copies, strict=True))
        context.report(
            {
                "project": target.id,
                "steps": [
                    {"id": copy.id, "title": copy.title, "from": original.id}
                    for original, copy in pairs
                ],
            },
            "\n".join(
                f"Duplicated {original.title!r} as {copy.id} in {target.title}"
                for original, copy in pairs
            ),
        )
        return 0

    return [
        CliCommand(
            path=("step", "list"),
            summary="The steps of one project, in order.",
            configure=project_arg,
            run=partial(_step_list, key_of=key_of),
            examples=("dplanner step list discovery",),
        ),
        CliCommand(
            path=("step", "show"),
            summary="One step: what it waits on, what waits on it, and its aspects.",
            configure=step_arg,
            run=partial(
                _step_show, key_of=key_of, auto_progresses=auto_progresses, branches_in=branches_in
            ),
            examples=("dplanner step show read-the-spec",),
        ),
        CliCommand(
            path=("step", "add"),
            summary="Add a step to a project — and author it in the same call: "
            "description, instruction, estimate, the feature it realises, figures.",
            configure=_configure_step_add,
            run=_step_add,
            examples=(
                "dplanner step add discovery 'Read the spec'",
                "dplanner step add discovery 'Draft the model' --after 'Read the spec'"
                " --describe-file model.md --agent-file - --days 3 --feature f2 --attach a1",
            ),
            edits_graph=project_of,
        ),
        CliCommand(
            path=("step", "rename"),
            summary="Change a step's title.",
            configure=_configure_step_rename,
            run=_step_rename,
            examples=("dplanner step rename read-the-spec --title 'Read the whole spec'",),
        ),
        CliCommand(
            path=("step", "remove"),
            summary="Delete a step. The links into it go with it, as one undoable change.",
            configure=step_arg,
            run=partial(_step_remove, remove_steps=remove_steps),
            examples=("dplanner step remove read-the-spec",),
            edits_graph=project_of_step,
        ),
        CliCommand(
            path=("step", "link"),
            summary="Say that one step waits on another.",
            configure=_configure_link,
            run=_step_link,
            examples=(
                "dplanner step link draft-the-model read-the-spec",
                "dplanner step link a b --kind relates",
            ),
            edits_graph=project_of_step,
        ),
        CliCommand(
            path=("step", "unlink"),
            summary="Remove a link between two steps.",
            configure=_configure_link,
            run=_step_unlink,
            examples=("dplanner step unlink draft-the-model read-the-spec",),
            edits_graph=project_of_step,
        ),
        CliCommand(
            path=("step", "isolate"),
            summary="Remove every link into or out of these steps; links among them stay.",
            configure=_configure_isolate,
            run=_step_isolate,
            examples=("dplanner step isolate draft-the-model review",),
            edits_graph=project_of_steps,
        ),
        CliCommand(
            path=("step", "redirect"),
            summary="Move the links hanging off these steps onto another step.",
            configure=_configure_redirect,
            run=_step_redirect,
            examples=(
                "dplanner step redirect draft-the-model --to rewrite-the-model",
                "dplanner step redirect s3 s4 --from review",
            ),
            edits_graph=project_of_steps,
        ),
        CliCommand(
            path=("step", "duplicate"),
            summary="Copy steps — aspects, prose, attachments and the links among them — "
            "into a project, one row below the originals.",
            configure=_configure_duplicate,
            run=_step_duplicate,
            examples=(
                "dplanner step duplicate read-the-spec",
                "dplanner step duplicate read-the-spec draft-the-model --into rollout",
            ),
            edits_graph=_project_of_duplicate,
        ),
    ]


def step_row(
    library: Library, step: Step, key_of: Callable[[Step], str] = _no_key
) -> dict[str, Any]:
    return {
        "id": step.id,
        "number": step.number,
        "key": key_of(step),
        "title": step.title,
        "requires": [other.id for other in library.requires(step.id)],
        "aspects": sorted(step.module_data),
    }


# -- step verbs ---------------------------------------------------------------------------------


def _step_list(
    context: CliContext, args: Namespace, key_of: Callable[[Step], str] = _no_key
) -> int:
    library = context.library
    project = find_project(library, args.project)
    rows = [step_row(library, step, key_of) for step in project.steps]
    text = (
        "\n".join(f"{row['key']:<4} {row['title']}  {row['id'][:8]}" for row in rows)
        or "No steps yet."
    )
    context.report({"steps": rows}, text)
    return 0


def _step_show(
    context: CliContext,
    args: Namespace,
    key_of: Callable[[Step], str] = _no_key,
    auto_progresses: Callable[[Step, Step], bool] = _plain,
    branches_in: Callable[[Project], Mapping[StepId, str]] = _no_branches,
) -> int:
    library = context.library
    step = find_step(library, args.step, context.current)
    project = library.project_of(step.id)
    waiting = library.requires(step.id)
    branch = branches_in(project).get(step.id, "")
    data = step_row(library, step, key_of) | {
        "project": project.id,
        "branch": branch,
        "dependents": [other.id for other in library.dependents(step.id)],
        "auto_progress": [other.id for other in waiting if auto_progresses(step, other)],
        "aspects": {key: dict(value) for key, value in sorted(step.module_data.items())},
        "text": sorted(step.module_text),
    }

    def named(others: Sequence[Step]) -> str:
        return ", ".join(f"{key_of(s)} {s.title}".strip() for s in others)

    def marked(source: Step) -> str:
        mark = " (auto-progress)" if auto_progresses(step, source) else ""
        return f"{key_of(source)} {source.title}".strip() + mark

    lines = [f"{key_of(step)} {step.title}".strip() + f"  {step.id}", f"  in {project.title}"]
    if branch:
        lines.append(f"  on branch: {branch}")
    if waiting:
        lines.append("  waits on: " + ", ".join(marked(source) for source in waiting))
    blocked = library.dependents(step.id)
    if blocked:
        lines.append("  blocks:   " + named(blocked))
    for key, value in sorted(step.module_data.items()):
        lines.append(f"  {key}: {json.dumps(value, sort_keys=True)}")
    for key in sorted(step.module_text):
        lines.append(f"  {key}: {len(step.module_text[key])} characters of prose")
    context.report(data, "\n".join(lines))
    return 0


def _configure_step_rename(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--title", required=True, help="the new title")


def _step_rename(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    context.apply(SetFieldCommand(step.id, "title", args.title))
    context.report(step_row(context.library, step), step.title)
    return 0


def _step_remove(
    context: CliContext, args: Namespace, remove_steps: RemoveSteps = remove_steps_command
) -> int:
    step = find_step(context.library, args.step, context.current)
    title = step.title
    context.apply(remove_steps(context.library, [step.id], "Remove"))
    context.report({"deleted": step.id}, f"Removed {title!r}")
    return 0


def _configure_link(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="the step that waits")
    parser.add_argument("on", help="the step it waits on")
    parser.add_argument(
        "--kind",
        default="requires",
        choices=sorted(EDGE_KINDS),
        help="requires orders the graph and refuses cycles; relates is a plain link",
    )


def _link_ends(context: CliContext, args: Namespace) -> tuple[Step, StepId]:
    library = context.library
    step = find_step(library, args.step, context.current)
    other = find_step(library, args.on, context.current)
    return step, other.id


def _step_link(context: CliContext, args: Namespace) -> int:
    step, other_id = _link_ends(context, args)
    targets = [*step.edges.get(args.kind, []), other_id]
    context.apply(SetEdgesCommand(step.id, args.kind, targets))
    context.report(
        step_row(context.library, step),
        f"{step.title!r} now {args.kind} {context.library.step(other_id).title!r}",
    )
    return 0


def _step_unlink(context: CliContext, args: Namespace) -> int:
    step, other_id = _link_ends(context, args)
    targets = [target for target in step.edges.get(args.kind, []) if target != other_id]
    context.apply(SetEdgesCommand(step.id, args.kind, targets))
    context.report(step_row(context.library, step), f"Unlinked from {step.title!r}")
    return 0


def _configure_redirect(parser: ArgumentParser) -> None:
    parser.add_argument(
        "steps",
        nargs="+",
        help="whose links move: id, folder name, or part of a title",
    )
    end = parser.add_mutually_exclusive_group(required=True)
    end.add_argument(
        "--to", metavar="STEP", help="the links pointing at these steps now point at STEP"
    )
    end.add_argument(
        "--from", dest="source", metavar="STEP", help="the links leaving these steps now leave STEP"
    )


def _step_redirect(context: CliContext, args: Namespace) -> int:
    """The canvas's Redirect, told which links by the steps they hang off.

    A terminal cannot pick arrows, so it names the steps and the end: ``--to`` takes every
    link *pointing at* them and ``--from`` every link *leaving* them. Both build the same
    ``Redirection`` the canvas mode does, so the two surfaces cannot come to different
    views of what is legal — a link that would close a cycle is reported and left alone.
    """
    library = context.library
    end: EdgeEnd = WAITER if args.to is not None else SOURCE
    anchor = find_step(library, args.to if args.to is not None else args.source, context.current)
    chosen: list[StepId] = []
    for needle in args.steps:
        step_id = find_step(library, needle, context.current).id
        if step_id not in chosen:
            chosen.append(step_id)
    plan = library.redirection(library.edges_of(chosen, end), anchor.id, end)
    if plan.moving:
        count = len(plan.moving)
        label = "Redirect Link" if count == 1 else f"Redirect {count} Links"
        context.apply(redirect_edges_command(library, plan, label))
    lines = [
        f"{library.step(waiter).title!r} now {kind} {library.step(source).title!r}"
        for waiter, kind, source in (plan.moved(edge) for edge in plan.moving)
    ]
    lines += [f"left alone: {why}" for _edge, why in plan.refused]
    data = {
        "anchor": anchor.id,
        "end": end,
        "moved": [
            {"waiter": waiter, "kind": kind, "source": source}
            for waiter, kind, source in (plan.moved(edge) for edge in plan.moving)
        ],
        "refused": [
            {"waiter": waiter, "kind": kind, "source": source, "reason": why}
            for (waiter, kind, source), why in plan.refused
        ],
    }
    context.report(data, "\n".join(lines) or "Nothing to redirect")
    return 0


def _configure_isolate(parser: ArgumentParser) -> None:
    parser.add_argument(
        "steps", nargs="+", help="the steps to cut loose: id, folder name, or part of a title"
    )


def _step_isolate(context: CliContext, args: Namespace) -> int:
    """The GUI's Isolate Steps: one command over ``Library.boundary_edges``."""
    library = context.library
    chosen: list[StepId] = []
    for needle in args.steps:
        step_id = find_step(library, needle, context.current).id
        if step_id not in chosen:
            chosen.append(step_id)
    boundary = library.boundary_edges(chosen)
    removed = [
        {"waiter": waiter, "kind": kind, "source": source} for waiter, kind, source in boundary
    ]
    if boundary:
        label = "Isolate Step" if len(chosen) == 1 else f"Isolate {len(chosen)} Steps"
        context.apply(remove_edges_command(library, boundary, label))
        text = "\n".join(
            f"{library.step(waiter).title!r} no longer {kind} {library.step(source).title!r}"
            for waiter, kind, source in boundary
        )
    else:
        text = "Nothing links in or out of " + ", ".join(
            repr(library.step(step_id).title) for step_id in chosen
        )
    context.report({"removed": removed}, text)
    return 0
