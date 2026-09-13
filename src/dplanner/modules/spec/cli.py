"""``dplanner spec …`` and ``dplanner topology …`` — a project's specification documents,
its figures, and its own account of how its graph is shaped.

This is the agent's surface: import a spec beside a project, read it (``show`` prints text,
markdown *and* PDFs — import extracts a PDF's text layer, and ``--page`` narrows to one
page; ``path`` still hands over the original file), ``render`` a page into an image and
``attach-to-step`` it so a figure travels with the step's briefing, and — when the spec is
replaced — ``diff`` what changed (PDFs diff by their text layers). What the spec *asks for*
is read into features (``dplanner step add --feature``, ``feature cite``), whose quotes
this module anchors through :func:`~dplanner.modules.spec.documents.anchor_sources`,
handed across by the composition root.

The **topology** is the project's prose beside the documents: ``topology set`` writes it
and ``topology show`` prints it — and records that it was read, which is what the gate in
``cli/gate.py`` checks before any verb reshapes the graph.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.gate import digest
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import body_from, find_project, find_step, project_arg, step_arg
from dplanner.cli.shaping import guide
from dplanner.core.text_diff import diff_hunks
from dplanner.domain.commands import EditTextCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.store import FilesFor
from dplanner.modules.spec.aspect import (
    MODULE_ID,
    TOPOLOGY_LABEL,
    read_attachments,
    read_topology,
    topology_edit,
    write_step_entry,
)
from dplanner.modules.spec.documents import (
    KIND_PDF,
    SpecDocument,
    SpecIndex,
    attach_asset,
    binary_refusal,
    blob_bytes,
    copied_to_step,
    default_name,
    document_digest,
    import_document,
    layer_from,
    matching_documents,
    new_document,
    read_index,
    record_asset,
    remove_document,
    write_index,
)
from dplanner.modules.spec.documents import anchor_sources as anchor_sources
from dplanner.modules.spec.pdf import render_page, split_pages
from dplanner.modules.spec.sourced import locator_line, owned_by_source, tree


def step_author() -> StepAuthor:
    """`step add`'s spec flag: the new step arrives with its figures beside it — through
    the same core the standalone verb uses, so the two paths cannot drift."""

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--attach",
            nargs="+",
            metavar="A",
            help="spec asset ids to copy beside the new step",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if not args.attach:
            return None
        project = context.library.project_of(step.id)
        attachments, files = copied_to_step(
            context.store.files, project, step, list(dict.fromkeys(args.attach))
        )
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write_step_entry(attachments)))
        return StepAuthored({"attachments": files}, f"attached {', '.join(args.attach)}")

    return StepAuthor(configure, author)


def lint_checks() -> list[LintCheck]:
    def topology_missing(
        _product: Library, project: Project, _files: FilesFor
    ) -> list[LintFinding]:
        """A project with steps and no account of its shape. The gate refuses the CLI
        until one exists; lint says the same thing about a plan built in a window."""
        if not project.steps or read_topology(project).strip():
            return []
        return [
            LintFinding(
                check="topology.missing",
                subject_id=project.id,
                subject=project.title,
                message="has no topology — say how its graph is shaped: "
                f"`dplanner topology set '{project.title}' --file -`",
            )
        ]

    def source_unfetched(
        _product: Library, project: Project, _files: FilesFor
    ) -> list[LintFinding]:
        """A source added but never fetched — connected to nothing yet, so the plan cites
        a place it has not read."""
        index = read_index(project)
        return [
            LintFinding(
                check="spec.source.unfetched",
                subject_id=project.id,
                subject=project.title,
                message=f"source {source.title!r} ({source.kind}) has never been fetched — "
                "connect and refresh it from the Specs tab",
            )
            for source in index.sources
            if not any(doc.source == source.id for doc in index.documents)
        ]

    return [topology_missing, source_unfetched]


def document_names(project: Project) -> list[str]:
    """The names a feature's source may point at — the editor's dropdown."""
    return [doc.name for doc in read_index(project).documents]


def digest_of(project: Project, document_name: str) -> str:
    """The document's digest as it is now — what the feature editor stamps a passage
    with; ``""`` for a name the index does not hold."""
    document = next((d for d in read_index(project).documents if d.name == document_name), None)
    return document_digest(document) if document is not None else ""


def commands(*, note_read: Callable[[str, str], None]) -> list[CliCommand]:
    """``note_read(project id, text)`` is the gate's ear: ``topology show`` calls it
    with what it printed, so the read is recorded where the gate will look."""

    def _topology_show(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        text = read_topology(project)
        if text.strip():
            note_read(project.id, text)
        # The read that is recorded is the project's own text, never what was printed: the
        # default travels with the build, and hashing it would un-read every project on
        # the day `shaping.md` gained a comma.
        default = "" if args.brief else guide()
        own = (
            text.rstrip("\n")
            if text.strip()
            else f"{project.title}: no topology yet — read the default shape below, then "
            f"write this project's own with `dplanner topology set {project.title!r} --file -`"
        )
        context.report(
            {
                "project": project.id,
                "topology": text,
                "digest": digest(text) if text else "",
                "default": default,
            },
            f"{own}\n\n---\n\n{default.rstrip()}" if default else own,
        )
        return 0

    return [
        CliCommand(
            path=("topology", "show"),
            summary="Print how a project's graph is shaped, and the default shape beside "
            "it, and record that you read it — the graph-editing verbs refuse until the "
            "current text has been read.",
            configure=_configure_topology_show,
            run=_topology_show,
            examples=("dplanner topology show 'Search rewrite'",),
        ),
        CliCommand(
            path=("topology", "set"),
            summary="Write a project's topology from a markdown file or stdin: what counts "
            "as a feature here, what follows one, where the milestones fall.",
            configure=_configure_topology_set,
            run=_topology_set,
            examples=("dplanner topology set 'Search rewrite' --file -",),
        ),
        CliCommand(
            path=("spec", "new"),
            summary="Create an empty markdown spec document beside a project — the "
            "in-app editor and `spec import` (same name replaces) both edit it.",
            configure=_configure_new,
            run=_new,
            examples=(
                "dplanner spec new 'Search rewrite' 'Auth flow'",
                "dplanner spec new 'Search rewrite' 'Auth flow' --name auth-spec",
            ),
        ),
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
            configure=project_arg,
            run=_list,
            examples=("dplanner spec list 'Search rewrite'",),
        ),
        CliCommand(
            path=("spec", "show"),
            summary="Print a spec document — a PDF prints its extracted text layer, "
            "and --page narrows to one page.",
            configure=_configure_show,
            run=_show,
            examples=(
                "dplanner spec show 'Search rewrite' auth-spec",
                "dplanner spec show 'Search rewrite' auth-spec --page 3",
            ),
        ),
        CliCommand(
            path=("spec", "path"),
            summary="Print the absolute path of a spec document's original file.",
            configure=_configure_versioned,
            run=_path,
            examples=("dplanner spec path 'Search rewrite' auth-spec",),
        ),
        CliCommand(
            path=("spec", "remove"),
            summary="Remove a spec document from the index; the file stays on disk for "
            "the workspace's VCS, and features read from it keep their source.",
            configure=_one_document,
            run=_remove,
            examples=("dplanner spec remove 'Search rewrite' auth-spec",),
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
            summary="Add an image beside a project's specs; it gets an asset id and a "
            "path markdown can link to.",
            configure=_configure_attach,
            run=_attach,
            examples=("dplanner spec attach 'Search rewrite' diagram.png",),
        ),
        CliCommand(
            path=("spec", "render"),
            summary="Render one page of a PDF spec to a PNG asset — the way a figure "
            "gets in front of a step's agent.",
            configure=_configure_render,
            run=_render,
            examples=("dplanner spec render 'Search rewrite' auth-spec --page 3",),
        ),
        CliCommand(
            path=("spec", "assets"),
            summary="List a project's spec assets: rendered pages and attached images.",
            configure=project_arg,
            run=_assets,
            examples=("dplanner spec assets 'Search rewrite'",),
        ),
        CliCommand(
            path=("spec", "attach-to-step"),
            summary="Copy spec assets beside a step so its briefing carries the figures "
            "(or --remove them).",
            configure=_configure_attach_to_step,
            run=_attach_to_step,
            examples=("dplanner spec attach-to-step 'Hash passwords' a1 a3",),
        ),
    ]


# -- parsers -----------------------------------------------------------------------------------


def _one_document(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("document", help="a spec document's name or filename")


def _configure_versioned(parser: ArgumentParser) -> None:
    _one_document(parser)
    parser.add_argument(
        "--previous", action="store_true", help="the version the last replace superseded"
    )


def _configure_show(parser: ArgumentParser) -> None:
    _configure_versioned(parser)
    parser.add_argument("--page", type=int, help="one page of a PDF's text (1-based)")


def _configure_new(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("title", help="the document's title; the body starts as '# <title>'")
    parser.add_argument("--name", help="the document's name (default: a slug of the title)")


def _configure_import(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("file", help="the document to copy in beside the project")
    parser.add_argument("--name", help="the document's name (default: a slug of the filename)")


def _configure_attach(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("image", help="the file to copy in beside the specs")


def _configure_topology_show(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument(
        "--brief",
        action="store_true",
        help="the project's own text alone, without the default shape",
    )


def _configure_topology_set(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--file", required=True, help="a markdown file, or - for stdin")


def _configure_render(parser: ArgumentParser) -> None:
    _one_document(parser)
    parser.add_argument("--page", type=int, required=True, help="the page to render (1-based)")
    parser.add_argument(
        "--scale", type=float, default=2.0, help="multiplies PDF points; 2.0 reads like 144 DPI"
    )


def _configure_attach_to_step(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument(
        "asset", nargs="+", help="asset ids from `dplanner spec assets`; several at once"
    )
    parser.add_argument("--remove", action="store_true", help="detach them from the step instead")


# -- shared lookups ----------------------------------------------------------------------------


def _document(project: Project, needle: str) -> SpecDocument:
    found = matching_documents(read_index(project).documents, needle)
    if len(found) == 1:
        return found[0]
    if not found:
        raise CliError(f"no spec document matching {needle!r} — see `dplanner spec list`")
    names = ", ".join(sorted(doc.name for doc in found))
    raise CliError(f"{needle!r} matches several spec documents — use a name: {names}")


def _refuse_sourced(index: SpecIndex, name: str) -> None:
    """A document a source fetched is the source's to change: refresh or remove the
    source from the Specs tab, where the credential is."""
    owner = owned_by_source(index, name)
    if owner is not None:
        raise CliError(
            f"{name!r} belongs to the source {owner.title!r} — refresh or remove the "
            "source from the Specs tab"
        )


def _blob(document: SpecDocument, previous: bool) -> str:
    if not previous:
        return document.file
    if document.previous is None:
        raise CliError(f"{document.name} has no previous version — it was never replaced")
    return document.previous


def _content(context: CliContext, project: Project, document: SpecDocument, blob: str) -> bytes:
    return blob_bytes(context.store.files(project.id, MODULE_ID), document, blob)


def _absolute(context: CliContext, project: Project, blob: str) -> str:
    return str(context.store.files(project.id, MODULE_ID).absolute(blob))


# -- verbs -------------------------------------------------------------------------------------


def _new(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    index = read_index(project)
    today = datetime.now(UTC).date().isoformat()
    area = context.store.files(project.id, MODULE_ID)
    docs, document = new_document(area, index.documents, args.title, today, name=args.name or "")
    context.apply(
        SetModuleDataCommand(project.id, MODULE_ID, write_index(replace(index, documents=docs)))
    )
    context.report(
        {"project": project.id, "document": document.name, "outcome": "added"},
        f"{document.name}: created — `dplanner spec import` with the same name replaces it",
    )
    return 0


def _import(context: CliContext, args: Namespace) -> int:
    source = Path(args.file)
    if not source.is_file():
        raise CliError(f"no such file: {args.file}")
    data = source.read_bytes()
    name = args.name or default_name(source.name)
    refusal = binary_refusal(data, source.name)
    if refusal is not None:
        raise CliError(refusal)

    project = find_project(context.library, args.project)
    index = read_index(project)
    _refuse_sourced(index, name)
    today = datetime.now(UTC).date().isoformat()
    area = context.store.files(project.id, MODULE_ID)
    docs, document, outcome = import_document(area, index.documents, name, data, source.name, today)
    if outcome != "unchanged":
        updated = replace(index, documents=docs)
        context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_index(updated)))
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
    project = find_project(context.library, args.project)
    index = read_index(project)
    lines: list[str] = []
    for row in tree(index):
        indent = "  " * row.depth
        if row.document is None and row.source is not None:
            source = row.source
            fetched = f"fetched {source.fetched}" if source.fetched else "never fetched"
            where = locator_line(source.locator)
            lines.append(
                f"{indent}[{source.kind}] {source.title}  ({source.id}, {fetched})  {where}"
            )
            continue
        doc = row.document
        assert doc is not None
        title = f" — {doc.title}" if doc.title and doc.title != doc.name else ""
        lines.append(
            f"{indent}{doc.name}{title}  ({doc.kind}, imported {doc.imported}, {doc.filename})"
            + ("  [previous kept]" if doc.previous else "")
        )
    context.report(
        {
            "project": project.id,
            "documents": [
                {
                    "name": doc.name,
                    "title": doc.label,
                    "filename": doc.filename,
                    "kind": doc.kind,
                    "imported": doc.imported,
                    "has_previous": doc.previous is not None,
                    **(
                        {
                            "source": doc.source,
                            "key": doc.key,
                            "version": doc.version,
                            "parent": doc.parent,
                        }
                        if doc.source
                        else {}
                    ),
                }
                for doc in index.documents
            ],
            "sources": [
                {
                    "id": source.id,
                    "kind": source.kind,
                    "title": source.title,
                    "locator": dict(source.locator),
                    "fetched": source.fetched,
                    "documents": len([doc for doc in index.documents if doc.source == source.id]),
                }
                for source in index.sources
            ],
        },
        "\n".join(lines) or "(no spec documents — add one with `dplanner spec import`)",
    )
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    document = _document(project, args.document)
    blob = _blob(document, args.previous)
    if document.kind == KIND_PDF:
        body = _pdf_text(context, project, document, blob)
        if args.page is not None:
            pages = split_pages(body)
            if not 1 <= args.page <= len(pages):
                raise CliError(f"no page {args.page} — {document.name} has {len(pages)} pages")
            body = pages[args.page - 1]
    elif args.page is not None:
        raise CliError(f"{document.name} is {document.kind} — pages are a PDF thing")
    else:
        body = _content(context, project, document, blob).decode("utf-8")
    context.report({"project": project.id, "document": document.name, "content": body}, body)
    return 0


def _pdf_text(context: CliContext, project: Project, document: SpecDocument, blob: str) -> str:
    return layer_from(context.store.files(project.id, MODULE_ID), document, blob)


def _path(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    document = _document(project, args.document)
    blob = _blob(document, args.previous)
    _content(context, project, document, blob)  # Refuse a path that would dangle.
    absolute = _absolute(context, project, blob)
    context.report({"project": project.id, "document": document.name, "path": absolute}, absolute)
    return 0


def _remove(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    document = _document(project, args.document)
    index = read_index(project)
    _refuse_sourced(index, document.name)
    docs = remove_document(index.documents, document.name)
    context.apply(
        SetModuleDataCommand(project.id, MODULE_ID, write_index(replace(index, documents=docs)))
    )
    context.report(
        {"project": project.id, "document": document.name},
        f"{document.name}: removed (the file stays on disk)",
    )
    return 0


def _diff(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    document = _document(project, args.document)
    if document.previous is None:
        raise CliError(f"{document.name} has no previous version — it was never replaced")
    if document.kind == KIND_PDF:
        # Text layers make PDFs diffable like anything else; the real files stay in the
        # JSON payload for an agent that wants the originals.
        before = _pdf_text(context, project, document, document.previous)
        after = _pdf_text(context, project, document, document.file)
        extra = {
            "previous": _absolute(context, project, document.previous),
            "current": _absolute(context, project, document.file),
        }
    else:
        before = _content(context, project, document, document.previous).decode("utf-8")
        after = _content(context, project, document, document.file).decode("utf-8")
        extra = {}
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
        }
        | extra,
        rendered or f"{document.name}: the two versions are identical",
    )
    return 0


def _attach(context: CliContext, args: Namespace) -> int:
    source = Path(args.image)
    if not source.is_file():
        raise CliError(f"no such file: {args.image}")
    project = find_project(context.library, args.project)
    index = read_index(project)
    area = context.store.files(project.id, MODULE_ID)
    name = attach_asset(area, source.read_bytes(), source.name)
    today = datetime.now(UTC).date().isoformat()
    assets, asset, outcome = record_asset(index.assets, name, "", None, today)
    if outcome != "unchanged":
        updated = replace(index, assets=assets)
        context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_index(updated)))
    context.report(
        {"project": project.id, "asset": asset.id, "file": name},
        f"{asset.id}: {name}\nReference it from a markdown spec as ![]({name}), or put it"
        f" in front of a step's agent with `dplanner spec attach-to-step <step> {asset.id}`",
    )
    return 0


def _render(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    document = _document(project, args.document)
    if document.kind != KIND_PDF:
        raise CliError(f"{document.name} is {document.kind} — only a PDF has pages to render")
    data = _content(context, project, document, document.file)
    try:
        image = render_page(data, args.page, args.scale)
    except ValueError as error:
        raise CliError(f"{document.name}: {error}") from error
    index = read_index(project)
    area = context.store.files(project.id, MODULE_ID)
    name = attach_asset(area, image, f"page{args.page}.png")
    today = datetime.now(UTC).date().isoformat()
    assets, asset, outcome = record_asset(index.assets, name, document.name, args.page, today)
    if outcome != "unchanged":
        updated = replace(index, assets=assets)
        context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_index(updated)))
    context.report(
        {
            "project": project.id,
            "document": document.name,
            "asset": asset.id,
            "page": args.page,
            "path": _absolute(context, project, name),
            "outcome": outcome,
        },
        f"{asset.id}: page {args.page} of {document.name} → {name}"
        + (" (already rendered — same image)" if outcome == "unchanged" else "")
        + f"\nAttach it to a step with `dplanner spec attach-to-step <step> {asset.id}`",
    )
    return 0


def _assets(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    index = read_index(project)
    context.report(
        {
            "project": project.id,
            "assets": [
                {
                    "id": asset.id,
                    "file": asset.file,
                    "document": asset.document,
                    "page": asset.page,
                    "imported": asset.imported,
                    "path": _absolute(context, project, asset.file),
                }
                for asset in index.assets
            ],
        },
        "\n".join(
            f"{asset.id}  {asset.file}"
            + (f"  ({asset.document}, page {asset.page})" if asset.document else "")
            for asset in index.assets
        )
        or "(no assets — `dplanner spec render` a PDF page, or `dplanner spec attach`)",
    )
    return 0


def _attach_to_step(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    project = context.library.project_of(step.id)
    wanted = list(dict.fromkeys(args.asset))
    if args.remove:
        # The copied blobs stay: content-addressed files are cheap, and another
        # attachment or an old briefing may still name them.
        doomed = set(wanted)
        attachments = [entry for entry in read_attachments(step) if entry.asset not in doomed]
        files: list[str] = []
        note = f"{step.title}: {', '.join(wanted)} detached (the files stay beside the step)"
    else:
        attachments, files = copied_to_step(context.store.files, project, step, wanted)
        note = f"{step.title}: attached {', '.join(wanted)}"
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write_step_entry(attachments)))
    context.report(
        {"step": step.id, "assets": wanted, "files": files, "attachments": len(attachments)},
        note,
    )
    return 0


def _topology_set(context: CliContext, args: Namespace) -> int:
    body = body_from(args.file)
    project = find_project(context.library, args.project)
    context.apply(EditTextCommand(topology_edit(project, body), label=TOPOLOGY_LABEL))
    context.report(
        {"project": project.id, "characters": len(body), "digest": digest(body)},
        f"{project.title}: topology set, {len(body)} characters — read it back with "
        f"`dplanner topology show {project.title!r}` before editing the graph",
    )
    return 0
