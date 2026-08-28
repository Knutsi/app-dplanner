"""``dplanner project …`` and ``dplanner step …`` — the graph, from a terminal.

Both nouns live here because a project *is* its step graph, and splitting them would put two
halves of one model in two packages. When a graph editor module arrives it can take the
``step`` group with it: a :class:`CliCommand` moves between packages without anything else
changing.

Every verb builds the same command from ``domain/commands.py`` that the menu does, so an
edit made here is undoable in a window open on the same product.

Qt-free by rule — see ``tests/test_architecture.py``.
"""

import json
from argparse import ArgumentParser, Namespace
from typing import Any

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lint import FilesFor, LintCheck, LintFinding
from dplanner.cli.lookup import find_project, find_step
from dplanner.domain.commands import (
    AddNodeCommand,
    CompositeCommand,
    EditTextCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import EDGE_KINDS, Product, Project, Step, StepId, TextEdit
from dplanner.domain.ordering import placed

PROJECT_ARG = "project id, folder name, or part of its title"
STEP_ARG = "step id, folder name, or part of its title"


def _one_project(parser: ArgumentParser) -> None:
    parser.add_argument("project", help=PROJECT_ARG)


def _one_step(parser: ArgumentParser) -> None:
    parser.add_argument("step", help=STEP_ARG)


def lint_checks() -> list[LintCheck]:
    def dangling_requires(
        _product: Product, project: Project, _files: FilesFor
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


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("project", "list"),
            summary="Every project in this product, with its step count.",
            run=_project_list,
            examples=("dplanner project list", "dplanner project list --json"),
        ),
        CliCommand(
            path=("project", "show"),
            summary="One project: its summary, its steps and the links between them.",
            configure=_one_project,
            run=_project_show,
            examples=("dplanner project show discovery",),
        ),
        CliCommand(
            path=("project", "create"),
            summary="Add a project to this product.",
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
            path=("project", "delete"),
            summary="Remove a project and every step in it.",
            configure=_one_project,
            run=_project_delete,
            examples=("dplanner project delete discovery",),
        ),
        CliCommand(
            path=("project", "clear-steps"),
            summary="Remove every step, keeping the project and its documents — "
            "the re-plan verb.",
            configure=_one_project,
            run=_project_clear_steps,
            examples=("dplanner project clear-steps discovery",),
        ),
        CliCommand(
            path=("project", "graph"),
            summary="The step graph as a Mermaid flowchart: waves as rows, requires as "
            "arrows. Paste it into a PR or a report.",
            configure=_one_project,
            run=_project_graph,
            examples=("dplanner project graph discovery",),
        ),
        CliCommand(
            path=("project", "export"),
            summary="Write one project — steps, links and aspects — as JSON.",
            configure=_one_project,
            run=_project_export,
            examples=("dplanner project export discovery > discovery.json",),
        ),
        CliCommand(
            path=("project", "import"),
            summary="Create a project from JSON on stdin, in export's shape.",
            configure=_configure_import,
            run=_project_import,
            examples=(
                "dplanner project import < discovery.json",
                "cat spec.json | dplanner project import",
            ),
        ),
        CliCommand(
            path=("step", "list"),
            summary="The steps of one project, in order.",
            configure=_one_project,
            run=_step_list,
            examples=("dplanner step list discovery",),
        ),
        CliCommand(
            path=("step", "show"),
            summary="One step: what it waits on, what waits on it, and its aspects.",
            configure=_one_step,
            run=_step_show,
            examples=("dplanner step show read-the-spec",),
        ),
        CliCommand(
            path=("step", "add"),
            summary="Add a step to a project.",
            configure=_configure_step_add,
            run=_step_add,
            examples=("dplanner step add discovery 'Read the spec'",),
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
            configure=_one_step,
            run=_step_remove,
            examples=("dplanner step remove read-the-spec",),
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
        ),
        CliCommand(
            path=("step", "unlink"),
            summary="Remove a link between two steps.",
            configure=_configure_link,
            run=_step_unlink,
            examples=("dplanner step unlink draft-the-model read-the-spec",),
        ),
    ]


# -- serialising --------------------------------------------------------------------------------


def project_document(product: Product, project: Project) -> dict[str, Any]:
    """One project as plain data — what ``export`` writes and ``import`` reads.

    Folder names are deliberately absent: they are presentation, frozen at creation, and an
    imported project earns its own. Module *file areas* — spec document blobs, attached
    images — are absent too: the document carries data and prose, not binaries.
    """
    return {
        "title": project.title,
        "summary": project.summary,
        # A project owns module data and prose of its own — its start date, its standing
        # agent instruction — so the document carries both. Without this, exporting and
        # importing quietly drops them.
        "aspects": {key: dict(value) for key, value in sorted(project.module_data.items())},
        "text": dict(sorted(project.module_text.items())),
        "steps": [
            {
                "id": step.id,
                "title": step.title,
                "edges": {kind: list(targets) for kind, targets in sorted(step.edges.items())},
                "aspects": {key: dict(value) for key, value in sorted(step.module_data.items())},
                "text": dict(sorted(step.module_text.items())),
            }
            for step in project.steps
        ],
    }


def _project_row(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "title": project.title,
        "summary": project.summary,
        "steps": len(project.steps),
    }


def _step_row(product: Product, step: Step) -> dict[str, Any]:
    return {
        "id": step.id,
        "title": step.title,
        "requires": [other.id for other in product.requires(step.id)],
        "aspects": sorted(step.module_data),
    }


# -- project verbs ------------------------------------------------------------------------------


def _project_list(context: CliContext, _args: Namespace) -> int:
    product = context.product
    rows = [_project_row(project) for project in product.projects]
    if not rows:
        context.report({"projects": []}, "No projects yet. `dplanner project create <title>`.")
        return 0
    width = max(len(row["title"]) for row in rows)
    text = "\n".join(
        f"{row['title']:<{width}}  {row['steps']:>3} steps  {row['id'][:8]}" for row in rows
    )
    context.report({"projects": rows}, text)
    return 0


def _project_show(context: CliContext, args: Namespace) -> int:
    product = context.product
    project = find_project(product, args.project)
    data = _project_row(project) | {"steps": [_step_row(product, step) for step in project.steps]}
    lines = [project.title, f"  {project.summary}" if project.summary else "", "  Steps:"]
    for step in project.steps:
        waiting = product.requires(step.id)
        suffix = f"  (after {', '.join(s.title for s in waiting)})" if waiting else ""
        lines.append(f"    {step.title}{suffix}  {step.id[:8]}")
    if not project.steps:
        lines.append("    none yet")
    context.report(data, "\n".join(line for line in lines if line))
    return 0


def _configure_create(parser: ArgumentParser) -> None:
    parser.add_argument("title", help="what the project is called")
    parser.add_argument("--summary", default="", help="one line on what it delivers")


def _project_create(context: CliContext, args: Namespace) -> int:
    project = Project(title=args.title, summary=args.summary)
    context.apply(AddNodeCommand(context.product.id, project))
    context.report(_project_row(project), f"Created {project.title!r}  {project.id}")
    return 0


def _configure_rename(parser: ArgumentParser) -> None:
    parser.add_argument("project", help=PROJECT_ARG)
    parser.add_argument("--title", help="the new title")
    parser.add_argument("--summary", help="the new summary")


def _project_rename(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    if args.title is None and args.summary is None:
        raise CliError("nothing to change — pass --title or --summary")
    if args.title is not None:
        context.apply(SetFieldCommand(project.id, "title", args.title))
    if args.summary is not None:
        context.apply(SetFieldCommand(project.id, "summary", args.summary))
    context.report(_project_row(project), f"{project.title}")
    return 0


def _project_delete(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    title, steps = project.title, len(project.steps)
    context.apply(RemoveNodeCommand(project.id))
    context.report(
        {"deleted": project.id, "steps": steps}, f"Deleted {title!r} and its {steps} steps"
    )
    return 0


def mermaid(product: Product, project: Project) -> str:
    """The step graph as a Mermaid flowchart — the same map the canvas draws, as text.

    Deliberately structure-only: waves become subgraphs so parallelism is visible at a
    glance, ``requires`` edges order them, and nothing else is styled in. The walk is
    ``placed()``, whose order is stable, so regenerating the chart after an unrelated edit
    diffs clean. Dangling edges are skipped, as everywhere ``requires()`` is read.
    """
    lines = ["flowchart TD"]
    rows = placed(product, project)
    if not rows:
        return "flowchart TD\n    %% no steps yet"
    node_ids = {row.step.id: f"s{row.step.id[:12]}" for row in rows}
    for wave in range(1, rows[-1].wave + 1):
        lines.append(f'    subgraph wave{wave}["Wave {wave}"]')
        for row in rows:
            if row.wave == wave:
                title = (row.step.title or "Untitled step").replace('"', "#quot;")
                lines.append(f'        {node_ids[row.step.id]}["{title}"]')
        lines.append("    end")
    for row in rows:
        for other in product.requires(row.step.id):
            lines.append(f"    {node_ids[other.id]} --> {node_ids[row.step.id]}")
    return "\n".join(lines)


def _project_graph(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    chart = mermaid(context.product, project)
    context.report({"project": project.id, "mermaid": chart}, chart)
    return 0


def _project_clear_steps(context: CliContext, args: Namespace) -> int:
    """The same composite the canvas's delete-N-steps gesture builds — one undoable
    object in a window, one transaction here. No confirmation, matching `project
    delete`: a run is a transaction and version control is the undo."""
    project = find_project(context.product, args.project)
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
    project = find_project(context.product, args.project)
    document = project_document(context.product, project)
    print(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False), file=context.out)
    return 0


def _configure_import(parser: ArgumentParser) -> None:
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

    project = Project(
        title=args.title or str(document.get("title", "Imported project")),
        summary=str(document.get("summary", "")),
    )
    context.apply(AddNodeCommand(context.product.id, project))
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
    for raw in raw_steps:
        step = Step(title=str(raw.get("title", "Untitled step")))
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
        _project_row(project),
        f"Imported {project.title!r} with {len(project.steps)} steps  {project.id}",
    )
    return 0


# -- step verbs ---------------------------------------------------------------------------------


def _step_list(context: CliContext, args: Namespace) -> int:
    product = context.product
    project = find_project(product, args.project)
    rows = [_step_row(product, step) for step in project.steps]
    text = "\n".join(f"{row['title']}  {row['id'][:8]}" for row in rows) or "No steps yet."
    context.report({"steps": rows}, text)
    return 0


def _step_show(context: CliContext, args: Namespace) -> int:
    product = context.product
    step = find_step(product, args.step)
    project = product.project_of(step.id)
    data = _step_row(product, step) | {
        "project": project.id,
        "dependents": [other.id for other in product.dependents(step.id)],
        "aspects": {key: dict(value) for key, value in sorted(step.module_data.items())},
        "text": sorted(step.module_text),
    }
    lines = [f"{step.title}  {step.id}", f"  in {project.title}"]
    waiting = product.requires(step.id)
    if waiting:
        lines.append("  waits on: " + ", ".join(s.title for s in waiting))
    blocked = product.dependents(step.id)
    if blocked:
        lines.append("  blocks:   " + ", ".join(s.title for s in blocked))
    for key, value in sorted(step.module_data.items()):
        lines.append(f"  {key}: {json.dumps(value, sort_keys=True)}")
    for key in sorted(step.module_text):
        lines.append(f"  {key}: {len(step.module_text[key])} characters of prose")
    context.report(data, "\n".join(lines))
    return 0


def _configure_step_add(parser: ArgumentParser) -> None:
    parser.add_argument("project", help=PROJECT_ARG)
    parser.add_argument("title", help="what the step is called")
    parser.add_argument(
        "--after",
        action="append",
        default=[],
        metavar="STEP",
        help="a step this one waits on; repeatable",
    )


def _step_add(context: CliContext, args: Namespace) -> int:
    product = context.product
    project = find_project(product, args.project)
    step = Step(title=args.title)
    context.apply(AddNodeCommand(project.id, step))
    waiting = [find_step(product, needle).id for needle in args.after]
    if waiting:
        context.apply(SetEdgesCommand(step.id, "requires", waiting))
    context.report(_step_row(product, step), f"Added {step.title!r} to {project.title}  {step.id}")
    return 0


def _configure_step_rename(parser: ArgumentParser) -> None:
    parser.add_argument("step", help=STEP_ARG)
    parser.add_argument("--title", required=True, help="the new title")


def _step_rename(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
    context.apply(SetFieldCommand(step.id, "title", args.title))
    context.report(_step_row(context.product, step), step.title)
    return 0


def _step_remove(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
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
    product = context.product
    step = find_step(product, args.step)
    other = find_step(product, args.on)
    return step, other.id


def _step_link(context: CliContext, args: Namespace) -> int:
    step, other_id = _link_ends(context, args)
    targets = [*step.edges.get(args.kind, []), other_id]
    context.apply(SetEdgesCommand(step.id, args.kind, targets))
    context.report(
        _step_row(context.product, step),
        f"{step.title!r} now {args.kind} {context.product.step(other_id).title!r}",
    )
    return 0


def _step_unlink(context: CliContext, args: Namespace) -> int:
    step, other_id = _link_ends(context, args)
    targets = [target for target in step.edges.get(args.kind, []) if target != other_id]
    context.apply(SetEdgesCommand(step.id, args.kind, targets))
    context.report(_step_row(context.product, step), f"Unlinked from {step.title!r}")
    return 0
