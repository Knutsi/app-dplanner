"""``dplanner project …`` and ``dplanner step …`` — the graph, from a terminal.

Both nouns live here because a project *is* its step graph, and splitting them would put two
halves of one model in two packages. When a graph editor module arrives it can take the
``step`` group with it: a :class:`CliCommand` moves between packages without anything else
changing.

Every verb builds the same command from ``domain/commands.py`` that the menu does, so an
edit made here is undoable in a window open on the same library.

Qt-free by rule — see ``tests/test_architecture.py``.
"""

import json
import shutil
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor
from dplanner.cli.lint import LintCheck, LintFinding, repository_finding
from dplanner.cli.lookup import (
    find_project,
    find_step,
    project_arg,
    project_of,
    project_of_step,
    step_arg,
)
from dplanner.core.fsio import slugify
from dplanner.core.storage.locations import (
    canonical_remote,
    find_repo_root,
    init_repo,
    origin_url,
)
from dplanner.core.storage.pointer import remove_from_index
from dplanner.domain.commands import (
    AddNodeCommand,
    CompositeCommand,
    EditTextCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
    remove_edges_command,
)
from dplanner.domain.model import EDGE_KINDS, Library, Project, Step, StepId, TextEdit
from dplanner.domain.ordering import placed
from dplanner.domain.relocate import RelocateError, move_project, target_in
from dplanner.domain.repositories import ACCEPTED, RepositoryFacts, repository_facts
from dplanner.domain.seed import seed_project
from dplanner.domain.store import FilesFor


def _no_key(_step: Step) -> str:
    return ""


def lint_checks() -> list[LintCheck]:
    def dangling_requires(
        _product: Library, project: Project, _files: FilesFor
    ) -> list[LintFinding]:
        # remove_child keeps edges naming a deleted step so undo restores the graph
        # exactly, and requires()/depths() silently skip them — this is the one reader
        # that says they are there.
        ids = {step.id for step in project.steps}
        return [
            LintFinding(
                check="graph.requires-dangling",
                subject_id=step.id,
                subject=step.title,
                message=f"waits on {target[:8]}, a step that no longer exists "
                "(the edge is kept so undo stays exact) — recreate the step, or ignore",
            )
            for step in project.steps
            for target in step.edges.get("requires", [])
            if target not in ids
        ]

    return [dangling_requires]


def commands(
    step_authors: Sequence[StepAuthor] = (), key_of: Callable[[Step], str] = _no_key
) -> list[CliCommand]:
    """``key_of`` is the step's readable key (``S7``, ``F3``) — the letter is a fact
    about aspects this file never reads, so the root hands the rule in and every row,
    listing and chart here prints the same key the canvas paints."""

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
        data, notes = _step_row(library, step, key_of), []
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

    return [
        CliCommand(
            path=("project", "list"),
            summary="Every project in this library, with its step count.",
            run=_project_list,
            examples=("dplanner project list", "dplanner project list --json"),
        ),
        CliCommand(
            path=("project", "show"),
            summary="One project: its summary, its steps and the links between them.",
            configure=project_arg,
            run=partial(_project_show, key_of=key_of),
            examples=("dplanner project show discovery",),
        ),
        CliCommand(
            path=("project", "create"),
            summary="Create a project directory inside a git repository and add it to the library.",
            configure=_configure_create,
            run=_project_create,
            examples=("dplanner project create 'Search rewrite' --summary 'Replace the index'",),
        ),
        CliCommand(
            path=("project", "rename"),
            summary="Change a project's title or summary.",
            configure=_configure_rename,
            run=_project_rename,
            examples=("dplanner project rename discovery --title 'Discovery phase'",),
        ),
        CliCommand(
            path=("project", "set"),
            summary="Say which code repository a project plans, where that code is checked "
            "out on this machine, or that the plan stays inside its code on purpose.",
            configure=_configure_set,
            run=_project_set,
            examples=(
                "dplanner project set discovery --repository https://github.com/acme/widget",
                "dplanner project set discovery --checkout ~/src/widget",
                "dplanner project set discovery --accept-colocation",
            ),
        ),
        CliCommand(
            path=("project", "move"),
            summary="Move a plan out of the repository it is in — usually the code it plans "
            "— into a plan repository, committing both sides.",
            configure=_configure_move,
            run=_project_move,
            examples=("dplanner project move discovery --into ~/plans",),
        ),
        CliCommand(
            path=("project", "delete"),
            summary="Remove a project from the library AND delete its directory "
            "from disk. `library remove` keeps the files.",
            configure=project_arg,
            run=_project_delete,
            examples=("dplanner project delete discovery",),
        ),
        CliCommand(
            path=("project", "clear-steps"),
            summary="Remove every step, keeping the project and its documents — the re-plan verb.",
            configure=project_arg,
            run=_project_clear_steps,
            examples=("dplanner project clear-steps discovery",),
            edits_graph=project_of,
        ),
        CliCommand(
            path=("project", "graph"),
            summary="The step graph as a Mermaid flowchart: waves as rows, requires as "
            "arrows. Paste it into a PR or a report.",
            configure=_configure_graph,
            run=partial(_project_graph, key_of=key_of),
            examples=(
                "dplanner project graph discovery",
                "dplanner project graph discovery --short",
            ),
        ),
        CliCommand(
            path=("project", "export"),
            summary="Write one project — steps, links and aspects — as JSON.",
            configure=project_arg,
            run=_project_export,
            examples=("dplanner project export discovery > discovery.json",),
        ),
        CliCommand(
            path=("project", "import"),
            summary="Create a project from JSON on stdin, in export's shape.",
            configure=_configure_import,
            run=_project_import,
            examples=("dplanner project import --dir ~/code/widget/planning < discovery.json",),
        ),
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
            run=partial(_step_show, key_of=key_of),
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
            summary="Delete a step. Links naming it are left alone, so undo stays exact.",
            configure=step_arg,
            run=_step_remove,
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
        ),
    ]


# -- serialising --------------------------------------------------------------------------------


def project_document(library: Library, project: Project) -> dict[str, Any]:
    """One project as plain data — what ``export`` writes and ``import`` reads.

    Folder names are deliberately absent: they are presentation, frozen at creation, and an
    imported project earns its own. Module *file areas* — spec document blobs, attached
    images — are absent too: the document carries data and prose, not binaries.
    """
    return {
        "title": project.title,
        "summary": project.summary,
        # The code repository it plans travels with the plan; where it is checked out on
        # a machine never does.
        "repository": project.repository,
        "colocation": project.colocation,
        # A project owns module data and prose of its own — its start date, its standing
        # agent instruction — so the document carries both. Without this, exporting and
        # importing quietly drops them.
        "aspects": {key: dict(value) for key, value in sorted(project.module_data.items())},
        "text": dict(sorted(project.module_text.items())),
        "steps": [
            {
                "id": step.id,
                "number": step.number,
                "title": step.title,
                "edges": {kind: list(targets) for kind, targets in sorted(step.edges.items())},
                "aspects": {key: dict(value) for key, value in sorted(step.module_data.items())},
                "text": dict(sorted(step.module_text.items())),
            }
            for step in project.steps
        ],
    }


def _facts(context: CliContext, project: Project) -> RepositoryFacts:
    return repository_facts(
        project, context.store.project_dir(project.id), context.store.checkout_of(project.id)
    )


def _project_row(context: CliContext, project: Project) -> dict[str, Any]:
    directory = context.store.project_dir(project.id)
    facts = _facts(context, project)
    return {
        "id": project.id,
        "title": project.title,
        "summary": project.summary,
        "steps": len(project.steps),
        "dir": str(directory),
        # The plan repository is derived — the directory decides it, git its remote; the
        # code repository is the project's own word; where the code is checked out is
        # this machine's, from the library file.
        "plan_root": str(facts.plan_root) if facts.plan_root else "",
        "plan_remote": facts.plan_remote,
        "repository": project.repository,
        "checkout": str(facts.checkout) if facts.checkout else "",
        "colocation": project.colocation,
        "state": facts.state,
    }


def _repository_lines(context: CliContext, project: Project) -> list[str]:
    """Where the plan and the code are, as ``project show`` and the setting verbs say it."""
    facts = _facts(context, project)
    title = project.title or project.folder_name
    plan = facts.plan_label or "not in a git repository"
    lines = [f"  plan: {plan}" + (f" ({facts.plan_root})" if facts.plan_root else "")]
    if project.repository:
        lines.append(f"  code: {facts.code_label}")
    else:
        lines.append(f"  code: not set — `dplanner project set '{title}' --repository URL`")
    if facts.checkout:
        lines.append(f"  checkout: {facts.checkout}")
    else:
        lines.append("  checkout: not on this machine")
    finding = repository_finding(project, facts)
    if finding is not None:
        lines.append(f"  ! {finding.message}")
    return lines


def _step_row(
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


# -- project verbs ------------------------------------------------------------------------------


def _project_list(context: CliContext, _args: Namespace) -> int:
    library = context.library
    rows = [_project_row(context, project) for project in library.projects]
    if not rows:
        context.report(
            {"projects": []},
            "No projects yet. `dplanner project create <title> --dir PATH`.",
        )
        return 0
    width = max(len(row["title"]) for row in rows)
    text = "\n".join(
        f"{row['title']:<{width}}  {row['steps']:>3} steps  {row['id'][:8]}" for row in rows
    )
    context.report({"projects": rows}, text)
    return 0


def _project_show(
    context: CliContext, args: Namespace, key_of: Callable[[Step], str] = _no_key
) -> int:
    library = context.library
    project = find_project(library, args.project)
    data = _project_row(context, project) | {
        "steps": [_step_row(library, step, key_of) for step in project.steps]
    }
    lines = [
        project.title,
        f"  {project.summary}" if project.summary else "",
        *_repository_lines(context, project),
        "  Steps:",
    ]
    for step in project.steps:
        waiting = library.requires(step.id)
        after = ", ".join(key_of(other) or other.title for other in waiting)
        suffix = f"  (after {after})" if waiting else ""
        lines.append(f"    {key_of(step):<4} {step.title}{suffix}  {step.id[:8]}")
    if not project.steps:
        lines.append("    none yet")
    context.report(data, "\n".join(line for line in lines if line))
    return 0


def _configure_graph(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument(
        "--short",
        action="store_true",
        help="compact labels: the steps' keys (s1, f2) as ids and titles cut to ~24"
        " characters — for graphs too wide to read, and the keys match the branches",
    )


def _configure_create(parser: ArgumentParser) -> None:
    parser.add_argument("title", help="what the project is called")
    parser.add_argument(
        "--dir",
        dest="directory",
        help="the project's directory, inside a plan repository",
    )
    parser.add_argument(
        "--in",
        dest="plan_repo",
        metavar="PLAN_REPO",
        help="a plan repository; the project lands in a folder named after its title",
    )
    parser.add_argument(
        "--init-repo",
        action="store_true",
        help="run git init on the directory when no repository encloses it",
    )
    parser.add_argument("--summary", default="", help="one line on what it delivers")
    parser.add_argument(
        "--repository",
        metavar="URL",
        default="",
        help="the code repository this project plans, as git names its remote",
    )
    parser.add_argument(
        "--checkout",
        metavar="PATH",
        default="",
        help="where this machine has that code checked out",
    )


def _create_target(args: Namespace) -> Path:
    if bool(args.directory) == bool(args.plan_repo):
        raise CliError("say where the project goes — exactly one of --dir DIR and --in PLAN_REPO")
    if args.directory:
        return Path(args.directory)
    return Path(args.plan_repo).expanduser() / slugify(args.title, fallback="project")


def _materialize(
    context: CliContext, directory: Path, title: str, *, init: bool, repository: str = ""
) -> Project:
    """Seed a project directory and attach it — the CLI's half of File ▸ New Project."""
    directory = directory.expanduser()
    if find_repo_root(directory) is None:
        if not init:
            raise CliError(
                f"{directory} is not inside a git repository — pass --init-repo, "
                "or run git init there first"
            )
        init_repo(directory)
    for existing in context.library.projects:
        if context.store.project_dir(existing.id).resolve() == directory.resolve():
            raise CliError(f"{directory} is already in the library")
    seed_project(directory, title, repository=repository)
    project = context.store.attach(directory)
    # Membership is applied directly: the CLI has no undo stack, and the GUI's half of
    # this verb is off the stack too — a repository cannot be un-inited.
    context.library.add_child(context.library.id, project)
    return project


def _project_create(context: CliContext, args: Namespace) -> int:
    project = _materialize(
        context,
        _create_target(args),
        args.title,
        init=args.init_repo,
        repository=args.repository.strip(),
    )
    if args.checkout:
        context.store.set_checkout(project.id, Path(args.checkout).expanduser().resolve())
    if args.summary:
        context.apply(SetFieldCommand(project.id, "summary", args.summary))
    context.report(
        _project_row(context, project),
        "\n".join(
            [f"Created {project.title!r}  {project.id}", *_repository_lines(context, project)]
        ),
    )
    return 0


def _configure_rename(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--title", help="the new title")
    parser.add_argument("--summary", help="the new summary")


def _project_rename(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    if args.title is None and args.summary is None:
        raise CliError("nothing to change — pass --title or --summary")
    if args.title is not None:
        context.apply(SetFieldCommand(project.id, "title", args.title))
    if args.summary is not None:
        context.apply(SetFieldCommand(project.id, "summary", args.summary))
    context.report(_project_row(context, project), f"{project.title}")
    return 0


def _configure_set(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument(
        "--repository",
        metavar="URL",
        help="the code repository this project plans, as git names its remote",
    )
    parser.add_argument(
        "--checkout", metavar="PATH", help="where this machine has that code checked out"
    )
    parser.add_argument(
        "--forget-checkout",
        action="store_true",
        help="drop the checkout recorded on this machine",
    )
    parser.add_argument(
        "--accept-colocation",
        action="store_true",
        help="the plan stays inside its code repository on purpose: stop warning",
    )
    parser.add_argument(
        "--warn-colocation", action="store_true", help="warn again about the plan's place"
    )


def _project_set(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    asked = (
        args.repository is not None,
        bool(args.checkout),
        args.forget_checkout,
        args.accept_colocation,
        args.warn_colocation,
    )
    if not any(asked):
        raise CliError(
            "nothing to set — pass --repository, --checkout, --forget-checkout, "
            "--accept-colocation or --warn-colocation"
        )
    notes: list[str] = []
    if args.repository is not None:
        context.apply(SetFieldCommand(project.id, "repository", args.repository.strip()))
    if args.checkout:
        checkout = Path(args.checkout).expanduser().resolve()
        context.store.set_checkout(project.id, checkout)
        origin = origin_url(checkout)
        if (
            project.repository
            and origin
            and canonical_remote(origin) != canonical_remote(project.repository)
        ):
            notes.append(f"  ! {checkout} has origin {origin}, not the project's code repository")
    elif args.forget_checkout:
        context.store.set_checkout(project.id, None)
    if args.accept_colocation:
        context.apply(SetFieldCommand(project.id, "colocation", ACCEPTED))
    elif args.warn_colocation:
        context.apply(SetFieldCommand(project.id, "colocation", ""))
    context.report(
        _project_row(context, project) | {"notes": notes},
        "\n".join([project.title, *_repository_lines(context, project), *notes]),
    )
    return 0


def _configure_move(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument(
        "--to", metavar="DIR", help="the plan's new directory, inside a plan repository"
    )
    parser.add_argument(
        "--into",
        metavar="PLAN_REPO",
        help="a plan repository; the plan lands in a folder named as its folder is now",
    )
    parser.add_argument(
        "--init-repo",
        action="store_true",
        help="run git init on the target's parent when no repository encloses it",
    )


def _project_move(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    if bool(args.to) == bool(args.into):
        raise CliError("say where the plan goes — exactly one of --to DIR and --into PLAN_REPO")
    target = (
        Path(args.to).expanduser()
        if args.to
        else target_in(Path(args.into).expanduser(), project.folder_name)
    )
    try:
        moved = move_project(context.store, project.id, target, init_repo=args.init_repo)
    except RelocateError as error:
        raise CliError(str(error)) from error
    committed = [
        name
        for name, done in (
            ("the repository it left", moved.source_committed),
            ("the plan repository", moved.target_committed),
        )
        if done
    ]
    lines = [
        f"Moved the plan of {project.title!r} to {moved.target}",
        "  committed in " + " and ".join(committed) if committed else "  nothing committed",
        *[f"  ! {note}" for note in moved.notes],
        *_repository_lines(context, project),
    ]
    context.report(
        {
            "project": project.id,
            "from": str(moved.source),
            "to": str(moved.target),
            "source_committed": moved.source_committed,
            "target_committed": moved.target_committed,
            "notes": list(moved.notes),
        },
        "\n".join(lines),
    )
    return 0


def _project_delete(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    directory = context.store.project_dir(project.id)
    title, steps = project.title, len(project.steps)
    context.library.remove_child(project.id)
    context.store.detach(project.id)
    remove_from_index(directory)  # A line that leads nowhere is a refusal on every walk.
    shutil.rmtree(directory, ignore_errors=True)
    context.report(
        {"deleted": project.id, "steps": steps, "dir": str(directory)},
        f"Deleted {title!r} and its {steps} steps, and removed {directory}",
    )
    return 0


SHORT_TITLE = 24  # Where a compact label cuts a title; enough to recognise, not to read.


def mermaid(
    library: Library,
    project: Project,
    short: bool = False,
    key_of: Callable[[Step], str] = _no_key,
) -> str:
    """The step graph as a Mermaid flowchart — the same map the canvas draws, as text.

    Deliberately structure-only: waves become subgraphs so parallelism is visible at a
    glance, ``requires`` edges order them, and nothing else is styled in. The walk is
    ``placed()``, whose order is stable, so regenerating the chart after an unrelated edit
    diffs clean. Dangling edges are skipped, as everywhere ``requires()`` is read.

    ``short`` swaps full titles for ``S7: Truncated title…`` labels over the steps' keys
    as node ids — narrow enough for a PR description, and the key is the name the branch
    and the PR carry, so a reader can match the chart to the work.
    """
    lines = ["flowchart TD"]
    rows = placed(library, project)
    if not rows:
        return "flowchart TD\n    %% no steps yet"

    def node_id(step: Step) -> str:
        return (key_of(step) or f"s{step.id[:12]}").lower() if short else f"s{step.id[:12]}"

    node_ids = {row.step.id: node_id(row.step) for row in rows}
    for wave in range(1, rows[-1].wave + 1):
        lines.append(f'    subgraph wave{wave}["Wave {wave}"]')
        for row in rows:
            if row.wave == wave:
                title = (row.step.title or "Untitled step").replace('"', "#quot;")
                if short:
                    cut = title if len(title) <= SHORT_TITLE else title[: SHORT_TITLE - 1] + "…"
                    title = f"{key_of(row.step) or row.index}: {cut}"
                lines.append(f'        {node_ids[row.step.id]}["{title}"]')
        lines.append("    end")
    for row in rows:
        for other in library.requires(row.step.id):
            lines.append(f"    {node_ids[other.id]} --> {node_ids[row.step.id]}")
    return "\n".join(lines)


def _project_graph(
    context: CliContext, args: Namespace, key_of: Callable[[Step], str] = _no_key
) -> int:
    project = find_project(context.library, args.project)
    chart = mermaid(context.library, project, short=args.short, key_of=key_of)
    context.report({"project": project.id, "mermaid": chart}, chart)
    return 0


def _project_clear_steps(context: CliContext, args: Namespace) -> int:
    """The same composite the canvas's delete-N-steps gesture builds — one undoable
    object in a window, one transaction here. No confirmation, matching `project
    delete`: a run is a transaction and version control is the undo."""
    project = find_project(context.library, args.project)
    doomed = list(project.steps)
    if doomed:
        context.apply(
            CompositeCommand(
                f"Clear {len(doomed)} Steps", [RemoveNodeCommand(step.id) for step in doomed]
            )
        )
    context.report(
        {"project": project.id, "removed": [step.id for step in doomed]},
        f"Removed all {len(doomed)} steps from {project.title!r} — "
        "specs, requirements and the start date stay",
    )
    return 0


def _project_export(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    document = project_document(context.library, project)
    # Deliberately not context.report(): export always emits JSON, --json or not — the
    # output IS the artefact. The one bare print in any module's cli.py.
    print(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False), file=context.out)
    return 0


def _configure_import(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--dir",
        required=True,
        dest="directory",
        help="the new project's directory, inside a git repository",
    )
    parser.add_argument(
        "--init-repo",
        action="store_true",
        help="run git init on the directory when no repository encloses it",
    )
    parser.add_argument(
        "--title", help="override the title in the document (default: use the document's)"
    )


def _project_import(context: CliContext, args: Namespace) -> int:
    """Read a project document from stdin.

    JSON rather than a PDF or a Markdown outline on purpose. Whoever is calling this — an
    agent working through a specification, most likely — has already read the source and
    understood it far better than a parser here ever would. This takes the understanding,
    not the document.
    """
    import sys

    try:
        document = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        raise CliError(f"stdin is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise CliError("expected a JSON object in the shape `dplanner project export` writes")

    title = args.title or str(document.get("title", "Imported project"))
    project = _materialize(
        context,
        Path(args.directory),
        title,
        init=args.init_repo,
        repository=str(document.get("repository", "")),
    )
    summary = str(document.get("summary", ""))
    if summary:
        context.apply(SetFieldCommand(project.id, "summary", summary))
    colocation = str(document.get("colocation", ""))
    if colocation:
        context.apply(SetFieldCommand(project.id, "colocation", colocation))
    for module_id, entry in dict(document.get("aspects", {})).items():
        context.apply(SetModuleDataCommand(project.id, str(module_id), dict(entry)))
    for module_id, body in dict(document.get("text", {})).items():
        edit = TextEdit(project.id, str(module_id), 0, "", str(body))
        context.apply(EditTextCommand(edit, label="Import"))

    # Ids in the document are the document's own. Steps get fresh ones and the links are
    # rewritten through this map, so importing the same file twice cannot collide.
    remapped: dict[str, StepId] = {}
    raw_steps = document.get("steps", [])
    if not isinstance(raw_steps, list):
        raise CliError("`steps` must be a list")
    taken: set[int] = set()
    for raw in raw_steps:
        step = Step(title=str(raw.get("title", "Untitled step")))
        # The document's numbers are kept where they are whole and unique — S7 stays S7
        # across an export and an import — and a step without one is dealt the next.
        number = raw.get("number")
        if isinstance(number, int) and not isinstance(number, bool) and 0 < number not in taken:
            step.number = number
            taken.add(number)
        step.module_data = {k: dict(v) for k, v in dict(raw.get("aspects", {})).items()}
        step.module_text = {k: str(v) for k, v in dict(raw.get("text", {})).items()}
        remapped[str(raw.get("id", step.id))] = step.id
        context.apply(AddNodeCommand(project.id, step))
    for raw in raw_steps:
        target = remapped.get(str(raw.get("id", "")))
        edges = dict(raw.get("edges", {}))
        for kind, ids in edges.items():
            if kind not in EDGE_KINDS or target is None:
                continue  # A kind this build does not know cannot be validated; skip it.
            wanted = [remapped[str(i)] for i in ids if str(i) in remapped]
            if wanted:
                context.apply(SetEdgesCommand(target, kind, wanted))

    context.report(
        _project_row(context, project),
        f"Imported {project.title!r} with {len(project.steps)} steps  {project.id}",
    )
    return 0


# -- step verbs ---------------------------------------------------------------------------------


def _step_list(
    context: CliContext, args: Namespace, key_of: Callable[[Step], str] = _no_key
) -> int:
    library = context.library
    project = find_project(library, args.project)
    rows = [_step_row(library, step, key_of) for step in project.steps]
    text = (
        "\n".join(f"{row['key']:<4} {row['title']}  {row['id'][:8]}" for row in rows)
        or "No steps yet."
    )
    context.report({"steps": rows}, text)
    return 0


def _step_show(
    context: CliContext, args: Namespace, key_of: Callable[[Step], str] = _no_key
) -> int:
    library = context.library
    step = find_step(library, args.step, context.current)
    project = library.project_of(step.id)
    data = _step_row(library, step, key_of) | {
        "project": project.id,
        "dependents": [other.id for other in library.dependents(step.id)],
        "aspects": {key: dict(value) for key, value in sorted(step.module_data.items())},
        "text": sorted(step.module_text),
    }

    def named(others: Sequence[Step]) -> str:
        return ", ".join(f"{key_of(s)} {s.title}".strip() for s in others)

    lines = [f"{key_of(step)} {step.title}".strip() + f"  {step.id}", f"  in {project.title}"]
    waiting = library.requires(step.id)
    if waiting:
        lines.append("  waits on: " + named(waiting))
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
    context.report(_step_row(context.library, step), step.title)
    return 0


def _step_remove(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    title = step.title
    context.apply(RemoveNodeCommand(step.id))
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
        _step_row(context.library, step),
        f"{step.title!r} now {args.kind} {context.library.step(other_id).title!r}",
    )
    return 0


def _step_unlink(context: CliContext, args: Namespace) -> int:
    step, other_id = _link_ends(context, args)
    targets = [target for target in step.edges.get(args.kind, []) if target != other_id]
    context.apply(SetEdgesCommand(step.id, args.kind, targets))
    context.report(_step_row(context.library, step), f"Unlinked from {step.title!r}")
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
