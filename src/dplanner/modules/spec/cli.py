"""``dplanner spec …`` — a project's specification documents and their requirements.

This is the agent's surface: import a spec beside a project, read it (``show`` prints text,
markdown *and* PDFs — import extracts a PDF's text layer, and ``--page`` narrows to one
page; ``path`` still hands over the original file), mark the requirements found in it —
``--quote`` is validated against the document and ``--page`` anchors it — link the steps
created from them, ``render`` a page into an image and ``attach-to-step`` it so a figure
travels with the step's briefing, and — when the spec is replaced — ``diff`` what changed
(PDFs diff by their text layers) and ``requirements`` to find the steps affected.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import find_project, find_step
from dplanner.core.text_diff import diff_hunks
from dplanner.domain.assets import attach
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Product, Project, Step
from dplanner.modules.spec.aspect import (
    MODULE_ID,
    SpecAttachment,
    read_attachments,
    read_links,
    write_step_entry,
)
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
    next_id,
    read_index,
    record_asset,
    remove_document,
    write_index,
)
from dplanner.modules.spec.pdf import find_quote, render_page, split_pages, text_blob_name
from dplanner.modules.spec.pdf import text_layer as extract_text_layer


def lint_checks() -> list[LintCheck]:
    def spec_findings(_product: Product, project: Project) -> list[LintFinding]:
        requirements = read_index(project).requirements
        known = {requirement.id for requirement in requirements}
        findings = [
            LintFinding(
                check="spec.requirement-unimplemented",
                subject_id=requirement.id,
                subject=requirement.title,
                message="no step implements it — "
                f"`dplanner spec link <step> {requirement.id}`",
            )
            for requirement in requirements
            if not linked_steps(project, requirement.id)
        ]
        for step in project.steps:
            links = read_links(step)
            findings += [
                LintFinding(
                    check="spec.link-dangling",
                    subject_id=step.id,
                    subject=step.title,
                    message=f"links {link}, which is not in the spec index — "
                    f"`dplanner spec link '{step.title}' {link} --remove`",
                )
                for link in links
                if link not in known
            ]
            # Only a project that has requirements can expect its steps to cite them.
            if requirements and not links:
                findings.append(
                    LintFinding(
                        check="spec.step-unlinked",
                        subject_id=step.id,
                        subject=step.title,
                        message="implements no requirement — "
                        f"`dplanner spec link '{step.title}' <requirement>`",
                    )
                )
        return findings

    return [spec_findings]


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
            summary="Remove a spec document and the requirements marked in it; "
            "the file stays on disk for the workspace's VCS.",
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
            configure=_one_project,
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
        CliCommand(
            path=("spec", "mark"),
            summary="Mark a requirement in a spec document, or update one by id; the "
            "quote is checked against the document.",
            configure=_configure_mark,
            run=_mark,
            examples=(
                "dplanner spec mark 'Search rewrite' auth-spec"
                " --title 'Passwords hashed with argon2id'"
                " --quote 'All stored credentials MUST use argon2id' --page 4",
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
            summary="Link a step to the requirements it implements (or --remove the links).",
            configure=_configure_link,
            run=_link,
            examples=("dplanner spec link 'Hash passwords' r1 r4 r7",),
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


def _configure_show(parser: ArgumentParser) -> None:
    _configure_versioned(parser)
    parser.add_argument("--page", type=int, help="one page of a PDF's text (1-based)")


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
    parser.add_argument(
        "--page", type=int, help="the page it sits on (default: where the quote is found)"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="refuse the mark when the quote is not found, instead of warning",
    )


def _configure_render(parser: ArgumentParser) -> None:
    _one_document(parser)
    parser.add_argument("--page", type=int, required=True, help="the page to render (1-based)")
    parser.add_argument(
        "--scale", type=float, default=2.0, help="multiplies PDF points; 2.0 reads like 144 DPI"
    )


def _configure_attach_to_step(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="step id, folder name, or part of its title")
    parser.add_argument(
        "asset", nargs="+", help="asset ids from `dplanner spec assets`; several at once"
    )
    parser.add_argument(
        "--remove", action="store_true", help="detach them from the step instead"
    )


def _configure_unmark(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("requirement", help="the requirement id to remove")


def _configure_requirements(parser: ArgumentParser) -> None:
    _one_project(parser)
    parser.add_argument("--document", help="only requirements marked in this document")


def _configure_link(parser: ArgumentParser) -> None:
    parser.add_argument("step", help="step id, folder name, or part of its title")
    parser.add_argument(
        "requirement",
        nargs="+",
        help="requirement ids in the step's project; several at once",
    )
    parser.add_argument("--remove", action="store_true", help="remove the links instead")


# -- shared lookups ----------------------------------------------------------------------------


def _document(project: Project, needle: str) -> SpecDocument:
    found = matching_documents(read_index(project).documents, needle)
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
    return str(context.store.files(project.id, MODULE_ID).absolute(blob))


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
    index = read_index(project)
    today = datetime.now(UTC).date().isoformat()
    area = context.store.files(project.id, MODULE_ID)
    docs, document, outcome = import_document(
        area, index.documents, name, data, source.name, today
    )
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
    project = find_project(context.product, args.project)
    index = read_index(project)
    docs = index.documents
    marked = {
        doc.name: [r.id for r in index.requirements if r.document == doc.name] for doc in docs
    }
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


def _pdf_text(
    context: CliContext, project: Project, document: SpecDocument, blob: str
) -> str:
    """The text layer: the file import wrote, or extracted in memory for a document
    imported before layers existed — a read verb never writes."""
    area = context.store.files(project.id, MODULE_ID)
    stored = area.read_bytes(text_blob_name(blob))
    if stored is not None:
        return stored.decode("utf-8")
    data = _content(context, project, document, blob)
    try:
        return extract_text_layer(data)
    except Exception as error:  # pdfium raises its own hierarchy.
        raise CliError(
            f"{document.name}: could not extract text ({error}) — read the original "
            f"from `dplanner spec path`"
        ) from error


def _path(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    document = _document(project, args.document)
    blob = _blob(document, args.previous)
    _content(context, project, document, blob)  # Refuse a path that would dangle.
    absolute = _absolute(context, project, blob)
    context.report({"project": project.id, "document": document.name, "path": absolute}, absolute)
    return 0


def _remove(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    document = _document(project, args.document)
    index = read_index(project)
    docs, requirements, dropped = remove_document(
        index.documents, index.requirements, document.name
    )
    updated = replace(index, documents=docs, requirements=requirements)
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_index(updated)))
    still_linked = {req.id: linked_steps(project, req.id) for req in dropped}
    note = f"{document.name}: removed"
    if dropped:
        note += f" with {len(dropped)} requirements"
    orphans = [req_id for req_id, steps in still_linked.items() if steps]
    if orphans:
        titles = ", ".join(
            sorted({step.title for req_id in orphans for step in still_linked[req_id]})
        )
        note += f" — still linked from {titles}; unlink with `dplanner spec link --remove`"
    context.report(
        {
            "project": project.id,
            "document": document.name,
            "requirements_removed": [req.id for req in dropped],
            "still_linked": {
                req_id: [step.id for step in steps]
                for req_id, steps in still_linked.items()
                if steps
            },
        },
        note,
    )
    return 0


def _diff(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
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
    project = find_project(context.product, args.project)
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
    project = find_project(context.product, args.project)
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
    project = find_project(context.product, args.project)
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


def _some(noun: str, ids: Sequence[str]) -> str:
    """"asset 'a1'" or "assets 'a1', 'a2'" — refusals read the same at any count."""
    listed = ", ".join(repr(entry) for entry in ids)
    return f"{noun}{'s' if len(ids) != 1 else ''} {listed}"


def linked_ids(project: Project, step: Step, ids: Sequence[str]) -> list[str]:
    """The step's links with ``ids`` added — refusing every unknown id in one message,
    before anything is written. Shared by ``spec link`` and ``step add --link``."""
    known = {req.id for req in read_index(project).requirements}
    unknown = [entry for entry in ids if entry not in known]
    if unknown:
        raise CliError(
            f"no {_some('requirement', unknown)} in {project.title!r} — "
            "see `dplanner spec requirements`"
        )
    links = read_links(step)
    return [*links, *[entry for entry in ids if entry not in links]]


def copied_to_step(
    context: CliContext, project: Project, step: Step, asset_ids: Sequence[str]
) -> tuple[list[SpecAttachment], list[str]]:
    """Copy each asset's blob beside the step; the updated attachments and copied names.

    Copied, not referenced: the step stays self-contained if the project's spec — or the
    whole asset — is later removed, and the briefing gets a real file. Every id is
    resolved and every blob read before the first copy, so a bad id refuses the batch.
    Shared by ``spec attach-to-step`` and ``step add --attach``.
    """
    index = read_index(project)
    by_id = {asset.id: asset for asset in index.assets}
    missing = [entry for entry in asset_ids if entry not in by_id]
    if missing:
        raise CliError(
            f"no {_some('asset', missing)} in {project.title!r} — see `dplanner spec assets`"
        )
    project_area = context.store.files(project.id, MODULE_ID)
    blobs: dict[str, bytes] = {}
    for asset_id in asset_ids:
        data = project_area.read_bytes(by_id[asset_id].file)
        if data is None:
            raise CliError(f"{asset_id}: {by_id[asset_id].file} is missing from the workspace")
        blobs[asset_id] = data
    attachments = read_attachments(step)
    copied: list[str] = []
    step_area = context.store.files(step.id, MODULE_ID)
    for asset_id in asset_ids:
        asset = by_id[asset_id]
        file = attach(step_area, blobs[asset_id], PurePosixPath(asset.file).name)
        copied.append(file)
        if not any(entry.asset == asset_id for entry in attachments):
            attachments = [
                *attachments,
                SpecAttachment(
                    file=file, document=asset.document, page=asset.page, asset=asset_id
                ),
            ]
    return attachments, copied


def _attach_to_step(context: CliContext, args: Namespace) -> int:
    step = find_step(context.product, args.step)
    project = context.product.project_of(step.id)
    wanted = list(dict.fromkeys(args.asset))
    if args.remove:
        # The copied blobs stay: content-addressed files are cheap, and another
        # attachment or an old briefing may still name them.
        doomed = set(wanted)
        attachments = [entry for entry in read_attachments(step) if entry.asset not in doomed]
        files: list[str] = []
        note = f"{step.title}: {', '.join(wanted)} detached (the files stay beside the step)"
    else:
        attachments, files = copied_to_step(context, project, step, wanted)
        note = f"{step.title}: attached {', '.join(wanted)}"
    context.apply(
        SetModuleDataCommand(step.id, MODULE_ID, write_step_entry(read_links(step), attachments))
    )
    context.report(
        {"step": step.id, "assets": wanted, "files": files, "attachments": len(attachments)},
        note,
    )
    return 0


def _mark(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    document = _document(project, args.document)
    index = read_index(project)
    quote_found, found_page = _validate_quote(context, project, document, args.quote)
    # Only a definite miss refuses: None means "nothing to check" (no quote, or a PDF
    # whose text cannot be read), and strictness must not punish the unknowable.
    if args.strict and quote_found is False:
        raise CliError(
            f"--strict: the quote was not found in {document.name} — check the wording "
            "against `dplanner spec show`, or drop --strict (PDF extraction can mangle text)"
        )
    page = args.page if args.page is not None else found_page
    requirement = Requirement(
        id=args.id or next_id([req.id for req in index.requirements], "r"),
        document=document.name,
        title=args.title,
        quote=args.quote,
        page=page,
    )
    requirements = index.requirements
    if requirement.id in [req.id for req in requirements]:
        requirements = [requirement if req.id == requirement.id else req for req in requirements]
        outcome = "updated"
    else:
        requirements = [*requirements, requirement]
        outcome = "marked"
    updated = replace(index, requirements=requirements)
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_index(updated)))
    note = f"{requirement.id}: {requirement.title} ({outcome} in {document.name})"
    if args.quote and quote_found is False:
        note += "\nwarning: the quote was not found in the document — check it anchors"
    elif args.page is not None and found_page is not None and args.page != found_page:
        note += f"\nwarning: the quote was found on page {found_page}, not {args.page}"
    context.report(
        {
            "project": project.id,
            "requirement": requirement.id,
            "outcome": outcome,
            "quote_found": quote_found,
            "page": page,
        },
        note,
    )
    return 0


def _validate_quote(
    context: CliContext, project: Project, document: SpecDocument, quote: str
) -> tuple[bool | None, int | None]:
    """(was the quote found, on which page). (None, None) when there is nothing to check.

    A warning, never a refusal: PDF extraction loses ligatures and hyphenation, and a
    mark that failed on rendering noise would teach people to stop quoting.
    """
    if not quote:
        return None, None
    if document.kind == KIND_PDF:
        try:
            layer = _pdf_text(context, project, document, document.file)
        except CliError:
            return None, None  # A PDF whose text cannot be read cannot refute a quote.
        page = find_quote(layer, quote)
        return page is not None, page
    body = _content(context, project, document, document.file).decode("utf-8")
    normalized = " ".join(quote.lower().split())
    return normalized in " ".join(body.lower().split()), None


def _unmark(context: CliContext, args: Namespace) -> int:
    project = find_project(context.product, args.project)
    index = read_index(project)
    if args.requirement not in [req.id for req in index.requirements]:
        raise CliError(f"no requirement {args.requirement!r} in {project.title!r}")
    remaining = [req for req in index.requirements if req.id != args.requirement]
    updated = replace(index, requirements=remaining)
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_index(updated)))
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
    requirements = read_index(project).requirements
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
                    "page": req.page,
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
    wanted = list(dict.fromkeys(args.requirement))
    if args.remove:
        doomed = set(wanted)
        links = [entry for entry in read_links(step) if entry not in doomed]
        note = f"{step.title}: no longer linked to {', '.join(wanted)}"
    else:
        links = linked_ids(project, step, wanted)
        note = f"{step.title}: linked to {', '.join(wanted)}"
    entry = write_step_entry(links, read_attachments(step))
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, entry))
    context.report(
        {"step": step.id, "requirements": sorted(set(links))},
        note,
    )
    return 0
