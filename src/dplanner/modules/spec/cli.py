"""``dplanner spec …`` — a project's specification documents and their requirements.

This is the agent's surface: import a spec beside a project, read it (``show`` for text,
``path`` for anything — a PDF is the agent's to read, not this tool's to parse), mark the
requirements found in it, link the steps created from them, and — when the spec is
replaced — ``diff`` what changed and ``requirements`` to find the steps affected.
"""

from argparse import ArgumentParser, Namespace
from datetime import UTC, datetime
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, find_step
from dplanner.core.text_diff import diff_hunks
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Project
from dplanner.modules.spec.aspect import MODULE_ID, read_links, write_links
from dplanner.modules.spec.documents import (
    KIND_PDF,
    Requirement,
    SpecDocument,
    attach_asset,
    binary_refusal,
    default_name,
    import_document,
    linked_steps,
    matching_documents,
    next_requirement_id,
    read_index,
    write_index,
)


def commands() -> list[CliCommand]:
    return [
        CliCommand(
            path=("spec", "import"),
            summary="Import a spec document (PDF, markdown, text) beside a project, "
            "or replace it — the previous version is kept for diffing.",
            configure=_configure_import,
            run=_import,
            examples=(
                "dplanner spec import 'Search rewrite' requirements.pdf",
                "dplanner spec import 'Search rewrite' v2.md --name auth-spec",
            ),
        ),
        CliCommand(
            path=("spec", "list"),
            summary="List a project's spec documents.",
            configure=_one_project,
            run=_list,
            examples=("dplanner spec list 'Search rewrite'",),
        ),
        CliCommand(
            path=("spec", "show"),
            summary="Print a text or markdown spec document; PDFs are read via `spec path`.",
            configure=_configure_versioned,
            run=_show,
            examples=("dplanner spec show 'Search rewrite' auth-spec",),
        ),
        CliCommand(
            path=("spec", "path"),
            summary="Print the absolute path of a spec document's file — read PDFs yourself.",
            configure=_configure_versioned,
            run=_path,
            examples=("dplanner spec path 'Search rewrite' auth-spec",),
        ),
        CliCommand(
            path=("spec", "diff"),
            summary="What changed between a spec document and its previous version.",
            configure=_one_document,
            run=_diff,
            examples=("dplanner spec diff 'Search rewrite' auth-spec",),
        ),
        CliCommand(
            path=("spec", "attach"),
            summary="Add an image beside a project's specs and print the path to link to.",
            configure=_configure_attach,
            run=_attach,
            examples=("dplanner spec attach 'Search rewrite' diagram.png",),
        ),
        CliCommand(
            path=("spec", "mark"),
            summary="Mark a requirement in a spec document, or update one by id.",
            configure=_configure_mark,
            run=_mark,
            examples=(
                "dplanner spec mark 'Search rewrite' auth-spec"
                " --title 'Passwords hashed with argon2id'"
                " --quote 'All stored credentials MUST use argon2id'",
            ),
        ),
        CliCommand(
            path=("spec", "unmark"),
            summary="Remove a requirement; steps that linked it keep their (now dangling) link.",
            configure=_configure_unmark,
            run=_unmark,
            examples=("dplanner spec unmark 'Search rewrite' r3",),
        ),
        CliCommand(
            path=("spec", "requirements"),
            summary="List a project's requirements and the steps linked to each.",
            configure=_configure_requirements,
            run=_requirements,
            examples=("dplanner spec requirements 'Search rewrite' --document auth-spec",),
        ),
        CliCommand(
            path=("spec", "link"),
            summary="Link a step to a requirement it implements (or --remove the link).",
            configure=_configure_link,
            run=_link,
            examples=("dplanner spec link 'Hash passwords' r1",),
        ),
    ]


# -- parsers -----------------------------------------------------------------------------------


def _one_project(parser: ArgumentParser) -> None:
    parser.add_argument("project", help="project id, folder name, or part of its title")


def _one_document(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("document", help="a spec document's name or filename")


def _configure_versioned(parser: ArgumentParser) -> None:
    _one_document(parser)
    parser.add_argument(
        "--previous", action="store_true", help="the version the last replace superseded"
    )


def _configure_import(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("file", help="the document to copy in beside the project")
    parser.add_argument("--name", help="the document's name (default: a slug of the filename)")


def _configure_attach(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("image", help="the file to copy in beside the specs")


def _configure_mark(parser: ArgumentParser) -> None:
    _one_document(parser)
    parser.add_argument("--title", required=True, help="the obligation, in one line")
    parser.add_argument("--id", help="requirement id (default: the next free rN)")
    parser.add_argument("--quote", default="", help="the passage anchoring it to the document")


def _configure_unmark(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("requirement", help="the requirement id to remove")


def _configure_requirements(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("--document", help="only requirements marked in this document")


def _configure_link(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="step id, folder name, or part of its title")
    parser.add_argument("requirement", help="the requirement id in the step's project")
    parser.add_argument("--remove", action="store_true", help="remove the link instead")


# -- shared lookups ----------------------------------------------------------------------------


def _document(project: Project, needle: str) -> SpecDocument:
    docs, _requirements = read_index(project)
    found = matching_documents(docs, needle)
    if len(found) == 1:
        return found[0]
    if not found:
        raise CliError(f"no spec document matching {needle!r} — see `dplanner spec list`")
    names = ", ".join(sorted(doc.name for doc in found))
    raise CliError(f"{needle!r} matches several spec documents — use a name: {names}")


def _blob(document: SpecDocument, previous: bool) -> str:
    if not previous:
        return document.file
    if document.previous is None:
        raise CliError(f"{document.name} has no previous version — it was never replaced")
    return document.previous


def _content(context: CliContext, project: Project, document: SpecDocument, blob: str) -> bytes:
    data = context.store.files(project.id, MODULE_ID).read_bytes(blob)
    if data is None:
        raise CliError(f"{document.name}: {blob} is missing from the workspace")
    return data


def _absolute(context: CliContext, project: Project, blob: str) -> str:
    area = context.store.files(project.id, MODULE_ID)
    return str(context.store.storage.root / Path(area.directory) / Path(blob))


# -- verbs -------------------------------------------------------------------------------------


def _import(context: CliContext, args: Namespace) -> int:
    source = Path(args.file)
    if not source.is_file():
        raise CliError(f"no such file: {args.file}")
    data = source.read_bytes()
    name = args.name or default_name(source.name)
    refusal = binary_refusal(data, source.name)
    if refusal is not None:
        raise CliError(refusal)

    project = find_project(context.product, args.project)
    docs, requirements = read_index(project)
    today = datetime.now(UTC).date().isoformat()
    area = context.store.files(project.id, MODULE_ID)
    docs, document, outcome = import_document(area, docs, name, data, source.name, today)
    if outcome != "unchanged":
        context.apply(
            SetModuleDataCommand(project.id, MODULE_ID, write_index(docs, requirements))
        )
    notes = {
        "added": f"{name}: added ({document.kind})",
        "replaced": f"{name}: replaced — previous version kept for `dplanner spec diff`",
        "unchanged": f"{name}: unchanged — same content already imported",
    }
    context.report(
        {"project": project.id, "document": document.name, "outcome": outcome},
        notes[outcome],
    )
    return 0


def _list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    docs, requirements = read_index(project)
    marked = {doc.name: [r.id for r in requirements if r.document == doc.name] for doc in docs}
    context.report(
        {
            "project": project.id,
            "documents": [
                {
                    "name": doc.name,
                    "filename": doc.filename,
                    "kind": doc.kind,
                    "imported": doc.imported,
                    "has_previous": doc.previous is not None,
                    "requirements": marked[doc.name],
                }
                for doc in docs
            ],
        },
        "\n".join(
            f"{doc.name}  ({doc.kind}, imported {doc.imported}, {doc.filename})"
            + ("  [previous kept]" if doc.previous else "")
            + (f"  {len(marked[doc.name])} requirements" if marked[doc.name] else "")
            for doc in docs
        )
        or "(no spec documents — add one with `dplanner spec import`)",
    )
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    document = _document(project, args.document)
    if document.kind == KIND_PDF:
        raise CliError(
            f"{document.name} is a PDF — read it yourself from `dplanner spec path "
            f"{args.project!r} {document.name}`"
        )
    data = _content(context, project, document, _blob(document, args.previous))
    body = data.decode("utf-8")
    context.report({"project": project.id, "document": document.name, "content": body}, body)
    return 0


def _path(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    document = _document(project, args.document)
    blob = _blob(document, args.previous)
    _content(context, project, document, blob)  # Refuse a path that would dangle.
    absolute = _absolute(context, project, blob)
    context.report({"project": project.id, "document": document.name, "path": absolute}, absolute)
    return 0


def _diff(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    document = _document(project, args.document)
    if document.previous is None:
        raise CliError(f"{document.name} has no previous version — it was never replaced")
    if document.kind == KIND_PDF:
        before = _absolute(context, project, document.previous)
        after = _absolute(context, project, document.file)
        context.report(
            {
                "project": project.id,
                "document": document.name,
                "previous": before,
                "current": after,
            },
            f"{document.name} is a PDF — compare the two versions yourself:\n"
            f"previous: {before}\ncurrent:  {after}",
        )
        return 0
    before = _content(context, project, document, document.previous).decode("utf-8")
    after = _content(context, project, document, document.file).decode("utf-8")
    hunks = diff_hunks(before, after)
    rendered = "\n".join(
        f"@ {hunk.pos}\n"
        + "".join(f"- {line}\n" for line in hunk.removed.splitlines())
        + "".join(f"+ {line}\n" for line in hunk.added.splitlines())
        for hunk in hunks
    )
    context.report(
        {
            "project": project.id,
            "document": document.name,
            "hunks": [
                {"pos": hunk.pos, "removed": hunk.removed, "added": hunk.added} for hunk in hunks
            ],
        },
        rendered or f"{document.name}: the two versions are identical",
    )
    return 0


def _attach(context: CliContext, args: Namespace) -> int:
    source = Path(args.image)
    if not source.is_file():
        raise CliError(f"no such file: {args.image}")
    project = find_project(context.product, args.project)
    area = context.store.files(project.id, MODULE_ID)
    name = attach_asset(area, source.read_bytes(), source.name)
    context.report(
        {"project": project.id, "asset": name},
        f"{name}\nReference it from a markdown spec as ![]({name})",
    )
    return 0


def _mark(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    document = _document(project, args.document)
    docs, requirements = read_index(project)
    requirement = Requirement(
        id=args.id or next_requirement_id(requirements),
        document=document.name,
        title=args.title,
        quote=args.quote,
    )
    existing = [req.id for req in requirements]
    if requirement.id in existing:
        requirements = [requirement if req.id == requirement.id else req for req in requirements]
        outcome = "updated"
    else:
        requirements = [*requirements, requirement]
        outcome = "marked"
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_index(docs, requirements)))
    context.report(
        {"project": project.id, "requirement": requirement.id, "outcome": outcome},
        f"{requirement.id}: {requirement.title} ({outcome} in {document.name})",
    )
    return 0


def _unmark(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    docs, requirements = read_index(project)
    if args.requirement not in [req.id for req in requirements]:
        raise CliError(f"no requirement {args.requirement!r} in {project.title!r}")
    remaining = [req for req in requirements if req.id != args.requirement]
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_index(docs, remaining)))
    still_linked = linked_steps(project, args.requirement)
    note = f"{args.requirement}: removed"
    if still_linked:
        titles = ", ".join(step.title for step in still_linked)
        note += f" — still linked from {titles}; unlink with `dplanner spec link --remove`"
    context.report(
        {
            "project": project.id,
            "requirement": args.requirement,
            "still_linked": [step.id for step in still_linked],
        },
        note,
    )
    return 0


def _requirements(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    _docs, requirements = read_index(project)
    if args.document is not None:
        name = _document(project, args.document).name
        requirements = [req for req in requirements if req.document == name]
    linked = {req.id: linked_steps(project, req.id) for req in requirements}
    context.report(
        {
            "project": project.id,
            "requirements": [
                {
                    "id": req.id,
                    "document": req.document,
                    "title": req.title,
                    "quote": req.quote,
                    "steps": [{"id": step.id, "title": step.title} for step in linked[req.id]],
                }
                for req in requirements
            ],
        },
        "\n".join(
            f"{req.id} ({req.document}): {req.title}"
            + (
                "\n  steps: " + ", ".join(step.title for step in linked[req.id])
                if linked[req.id]
                else "\n  steps: (none — create them and `dplanner spec link`)"
            )
            for req in requirements
        )
        or "(no requirements — mark them with `dplanner spec mark`)",
    )
    return 0


def _link(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
    project = context.product.project_of(step.id)
    _docs, requirements = read_index(project)
    known = {req.id for req in requirements}
    links = read_links(step)
    if args.remove:
        links = [entry for entry in links if entry != args.requirement]
        note = f"{step.title}: no longer linked to {args.requirement}"
    else:
        if args.requirement not in known:
            raise CliError(
                f"no requirement {args.requirement!r} in {project.title!r} — "
                "see `dplanner spec requirements`"
            )
        if args.requirement not in links:
            links = [*links, args.requirement]
        note = f"{step.title}: linked to {args.requirement}"
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write_links(links)))
    context.report(
        {"step": step.id, "requirements": sorted(set(links))},
        note,
    )
    return 0
