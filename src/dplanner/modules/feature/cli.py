"""``dplanner feature …`` — the project's catalogue of features, and which step realises
each.

A feature is read out of a spec (``feature add --document … --quote …``: the quote is
checked against the document the way a requirement's once was) or added by hand, and
lives in the catalogue whether or not it is on the graph yet. ``feature set`` makes a step
the instance of one — or mints a record for a step that is a feature nobody catalogued —
and ``step add --feature`` does the same for a step being born. One record has one
instance; a second is refused, because a feature is implemented once.

What a feature *gathers* is not here: that is ``dplanner scope show``, one verb over every
kind of collector, because a check, a feature and a milestone are one derivation asked
three ways. The quote check arrives as ``anchor`` from the spec module, handed across by
the composition root, so this file never learns how a document is stored.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import (
    body_from,
    find_project,
    find_step,
    project_arg,
    project_of,
    project_of_step,
    step_arg,
)
from dplanner.domain.assets import attach
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.store import FilesFor
from dplanner.modules.feature.aspect import MODULE_ID, clear, read, write
from dplanner.modules.feature.catalogue import (
    FeatureRecord,
    FeatureSource,
    find_record,
    image_paths,
    instance_of,
    mint_for_step,
    next_feature_id,
    placements,
    read_catalogue,
    registration,
    summary_line,
    unregistered,
    with_record,
    without_record,
    write_catalogue,
)

# (files, project, document name, quote) → (found?, pages). None: nothing to check.
type Anchor = Callable[[FilesFor, Project, str, str], tuple[bool | None, list[int]]]


def commands(*, anchor: Anchor) -> list[CliCommand]:
    def _add(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        records = read_catalogue(project)
        if args.id and any(record.id == args.id for record in records):
            raise CliError(
                f"{args.id} already exists in {project.title!r} — `dplanner feature edit` it"
            )
        record = FeatureRecord(
            id=args.id or next_feature_id(records),
            title=args.title,
            description=body_from(args.describe_file) if args.describe_file else "",
        )
        record, warning = _sourced(context, project, record, args, anchor)
        if args.image:
            record = replace(
                record, images=tuple(_attached(context, project, path) for path in args.image)
            )
        context.apply(
            SetModuleDataCommand(project.id, MODULE_ID, write_catalogue([*records, record]))
        )
        note = f"{record.id}: {record.title} — not placed yet; `dplanner step add " + (
            f"{project.title!r} {record.title!r} --feature {record.id} --after …`"
        )
        context.report(_row(context, project, record) | {"outcome": "added"}, note + warning)
        return 0

    def _edit(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        record = find_record(project, args.feature)
        if args.title:
            record = replace(record, title=args.title)
        if args.describe_file:
            record = replace(record, description=body_from(args.describe_file))
        if args.clear_source:
            record = replace(record, source=None)
        record, warning = _sourced(context, project, record, args, anchor)
        context.apply(
            SetModuleDataCommand(
                project.id, MODULE_ID, write_catalogue(with_record(read_catalogue(project), record))
            )
        )
        context.report(
            _row(context, project, record) | {"outcome": "updated"},
            f"{record.id}: {record.title} — updated" + warning,
        )
        return 0

    return [
        CliCommand(
            path=("feature", "list"),
            summary="A project's features — placed on the graph or not yet — and the step "
            "that realises each.",
            configure=_configure_list,
            run=_list,
            examples=(
                "dplanner feature list discovery",
                "dplanner feature list discovery --document auth-spec --json",
            ),
        ),
        CliCommand(
            path=("feature", "show"),
            summary="One feature in full: its description, where in the spec it came "
            "from, its images, and the step that realises it.",
            configure=_configure_feature,
            run=_show,
            examples=("dplanner feature show discovery f1",),
        ),
        CliCommand(
            path=("feature", "add"),
            summary="Add a feature to a project's catalogue — read from a spec passage "
            "(the quote is checked against the document) or by hand.",
            configure=_configure_add,
            run=_add,
            examples=(
                "dplanner feature add discovery 'Bulk import' --document auth-spec"
                " --quote 'Operators MUST be able to import a CSV of readings' --page 4",
                "dplanner feature add discovery 'Dark mode' --describe-file -",
            ),
            edits_graph=project_of,
        ),
        CliCommand(
            path=("feature", "edit"),
            summary="Change a feature's title, description or spec source.",
            configure=_configure_edit,
            run=_edit,
            examples=(
                "dplanner feature edit discovery f1 --title 'Bulk CSV import'",
                "dplanner feature edit discovery f1 --document auth-spec --quote '…' --page 5",
            ),
        ),
        CliCommand(
            path=("feature", "attach"),
            summary="Add an image showing a feature — a mock-up, a rendered spec page — "
            "beside the project; the briefing of its step carries it.",
            configure=_configure_attach,
            run=_attach,
            examples=("dplanner feature attach discovery f1 mockup.png",),
        ),
        CliCommand(
            path=("feature", "remove"),
            summary="Remove a feature from the catalogue; the step that realised it "
            "becomes a plain step.",
            configure=_configure_feature,
            run=_remove,
            examples=("dplanner feature remove discovery f1",),
            edits_graph=project_of,
        ),
        CliCommand(
            path=("feature", "set"),
            summary="Make a step the instance of a feature (--feature), or catalogue the "
            "step as a new feature of its own.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner feature set 'Bulk import' --feature f1",
                "dplanner feature set 'Bulk import'",
            ),
            edits_graph=project_of_step,
        ),
        CliCommand(
            path=("feature", "clear"),
            summary="A step is no longer a feature's instance; the feature stays in the "
            "catalogue, unplaced.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner feature clear 'Bulk import'",),
            edits_graph=project_of_step,
        ),
    ]


def step_author() -> StepAuthor:
    """`step add`'s feature flag: the new step is born as a feature's instance — of the
    record named, or of a fresh one titled like the step when the flag is bare."""

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--feature",
            nargs="?",
            const="",
            metavar="F",
            help="the feature this step realises (an id from `feature list`); bare, the "
            "step is catalogued as a new feature of its own",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if args.feature is None:
            return None
        project = context.library.project_of(step.id)
        record = _placed(context, project, step, args.feature)
        return StepAuthored({"feature": record.id}, f"feature {record.id} ({record.title})")

    return StepAuthor(configure, author)


def lint_checks(*, anchor: Anchor) -> list[LintCheck]:
    def catalogue_findings(
        _product: Library, project: Project, _files: FilesFor
    ) -> list[LintFinding]:
        records = read_catalogue(project)
        known = {record.id for record in records}
        placed = placements(project)
        findings = [
            LintFinding(
                check="feature.unplaced",
                subject_id=record.id,
                subject=record.title,
                message="no step realises it — "
                f"`dplanner step add '{project.title}' '{record.title}' "
                f"--feature {record.id} --after <its work>`",
            )
            for record in records
            if record.id not in placed
        ]
        for record in records:
            steps = placed.get(record.id, [])
            if len(steps) > 1:
                titles = ", ".join(repr(step.title) for step in steps)
                findings.append(
                    LintFinding(
                        check="feature.duplicate",
                        subject_id=record.id,
                        subject=record.title,
                        message=f"realised by {len(steps)} steps ({titles}) — a feature is "
                        "implemented once; `dplanner feature clear` the extra",
                    )
                )
        for step in project.steps:
            record_id = read(step)
            if record_id and record_id not in known:
                findings.append(
                    LintFinding(
                        check="feature.dangling",
                        subject_id=step.id,
                        subject=step.title,
                        message=f"names feature {record_id}, which is not in the catalogue — "
                        f"`dplanner feature clear '{step.title}'`, or `feature set` it to one",
                    )
                )
        findings += [
            LintFinding(
                check="feature.unregistered",
                subject_id=step.id,
                subject=step.title,
                message="is a feature with no catalogue record — "
                f"`dplanner feature set '{step.title}'` registers it",
            )
            for step in unregistered(project)
        ]
        return findings

    def unanchored_quotes(
        _product: Library, project: Project, files: FilesFor
    ) -> list[LintFinding]:
        """A feature whose quote no longer appears in its document — the spec was
        replaced and the source drifted. Re-checked here rather than stored at add
        time, because a stored answer is stale the moment `spec import` replaces the
        document with no window running to notice."""
        findings = []
        for record in read_catalogue(project):
            if record.source is None or not record.source.quote:
                continue
            found, _pages = anchor(files, project, record.source.document, record.source.quote)
            if found is False:
                findings.append(
                    LintFinding(
                        check="feature.quote-unanchored",
                        subject_id=record.id,
                        subject=record.title,
                        message=f"its quote no longer anchors in {record.source.document} — "
                        "re-read the document and re-source it: `dplanner feature edit "
                        f"'{project.title}' {record.id} --document {record.source.document} "
                        "--quote …`",
                    )
                )
        return findings

    return [catalogue_findings, unanchored_quotes]


# -- parsers -----------------------------------------------------------------------------------


def _configure_list(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--document", help="only features read from this spec document")


def _configure_feature(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("feature", help="a feature id from `feature list`, or part of its title")


def _source_args(parser: ArgumentParser) -> None:
    parser.add_argument("--document", help="the spec document it was read from")
    parser.add_argument("--quote", default="", help="the passage it was read from")
    parser.add_argument(
        "--page", type=int, help="the page it sits on (default: where the quote is found)"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="refuse when the quote is not found in the document, instead of warning",
    )
    parser.add_argument(
        "--describe-file", metavar="FILE", help="a markdown description, or - for stdin"
    )


def _configure_add(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("title", help="what the feature is called")
    parser.add_argument("--id", help="feature id (default: the next free fN)")
    _source_args(parser)
    parser.add_argument(
        "--image", nargs="+", metavar="FILE", help="images showing the feature, copied in"
    )


def _configure_edit(parser: ArgumentParser) -> None:
    _configure_feature(parser)
    parser.add_argument("--title", help="the new title")
    _source_args(parser)
    parser.add_argument(
        "--clear-source", action="store_true", help="forget where in the spec it came from"
    )


def _configure_attach(parser: ArgumentParser) -> None:
    _configure_feature(parser)
    parser.add_argument("file", help="the image to copy in beside the project")


def _configure_set(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument(
        "--feature",
        metavar="F",
        help="the feature this step realises (omitted: the step is catalogued as a new one)",
    )


# -- shared halves -----------------------------------------------------------------------------


def _sourced(
    context: CliContext, project: Project, record: FeatureRecord, args: Namespace, anchor: Anchor
) -> tuple[FeatureRecord, str]:
    """``record`` with the source ``args`` name, and the warning line to print, if any.

    Only a definite miss refuses under ``--strict``: None means "nothing to check" (no
    quote, or a PDF whose text cannot be read), and strictness must not punish the
    unknowable. A quote can recur; ``--page`` naming any occurrence is disambiguation,
    not a miss.
    """
    if args.document is None:
        if args.quote or args.page is not None:
            raise CliError("--quote and --page need --document: which spec was it read from?")
        return record, ""
    found, pages = anchor(context.store.files, project, args.document, args.quote)
    if args.strict and found is False:
        raise CliError(
            f"--strict: the quote was not found in {args.document} — check the wording "
            "against `dplanner spec show`, or drop --strict (PDF extraction can mangle text)"
        )
    page = args.page if args.page is not None else (pages[0] if pages else None)
    warning = ""
    if args.quote and found is False:
        warning = "\nwarning: the quote was not found in the document — check it anchors"
    elif args.page is not None and pages and args.page not in pages:
        anchored = ", ".join(str(number) for number in pages)
        warning = (
            f"\nwarning: the quote was not found on page {args.page} — it anchors on {anchored}"
        )
    return (
        replace(record, source=FeatureSource(document=args.document, quote=args.quote, page=page)),
        warning,
    )


def _attached(context: CliContext, project: Project, path: str) -> str:
    source = Path(path)
    if not source.is_file():
        raise CliError(f"no such file: {path}")
    return attach(context.store.files(project.id, MODULE_ID), source.read_bytes(), source.name)


def _placed(context: CliContext, project: Project, step: Step, feature: str) -> FeatureRecord:
    """Make ``step`` the instance of ``feature`` — or of a fresh record when ``feature`` is
    empty — refusing a record another step already realises. Shared by ``feature set``
    and ``step add --feature``, so the two cannot disagree about what "once" means."""
    if not feature:
        record = mint_for_step(read_catalogue(project), step)
        for command in registration(project, step):
            context.apply(command)
        return record
    record = find_record(project, feature)
    holder = instance_of(project, record.id)
    if holder is not None and holder.id != step.id:
        raise CliError(
            f"{record.id} ({record.title}) is already realised by {holder.title!r} — a "
            f"feature is implemented once; `dplanner feature clear {holder.title!r}` first"
        )
    if holder is None:
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(record.id)))
    return record


def _row(context: CliContext, project: Project, record: FeatureRecord) -> dict[str, object]:
    instance = instance_of(project, record.id)
    return {
        "project": project.id,
        "feature": record.id,
        "title": record.title,
        "description": record.description,
        "source": (
            {
                "document": record.source.document,
                "quote": record.source.quote,
                "page": record.source.page,
            }
            if record.source is not None
            else None
        ),
        "images": list(image_paths(context.store.files, project.id, record)),
        "step": {"id": instance.id, "title": instance.title} if instance is not None else None,
    }


# -- verbs -------------------------------------------------------------------------------------


def _list(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    records = read_catalogue(project)
    if args.document is not None:
        records = [
            record
            for record in records
            if record.source is not None and record.source.document == args.document
        ]
    rows = [_row(context, project, record) for record in records]
    lines = [
        f"{record.id:<4} {record.title}  — {summary_line(record, instance_of(project, record.id))}"
        for record in records
    ]
    for step in unregistered(project):
        lines.append(f"     {step.title}  — feature step with no record; `dplanner feature set`")
    context.report(
        {"project": project.id, "features": rows},
        "\n".join(lines)
        or "(no features yet — `dplanner feature add`, or read them out of a spec)",
    )
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    record = find_record(project, args.feature)
    row = _row(context, project, record)
    instance = instance_of(project, record.id)
    lines = [f"{record.id}: {record.title}", summary_line(record, instance)]
    if record.source is not None and record.source.quote:
        lines += [f"  > {quoted}" for quoted in record.source.quote.splitlines()]
    if record.description:
        lines += ["", record.description.rstrip("\n")]
    for path in image_paths(context.store.files, project.id, record):
        lines.append(f"image: {path}")
    if instance is not None:
        lines += ["", f"what flows into it: `dplanner scope show {instance.title!r}`"]
    context.report(row, "\n".join(lines))
    return 0


def _attach(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    record = find_record(project, args.feature)
    name = _attached(context, project, args.file)
    if name not in record.images:
        record = replace(record, images=(*record.images, name))
        context.apply(
            SetModuleDataCommand(
                project.id, MODULE_ID, write_catalogue(with_record(read_catalogue(project), record))
            )
        )
    path = str(context.store.files(project.id, MODULE_ID).absolute(name))
    context.report(
        {"project": project.id, "feature": record.id, "asset": name, "path": path},
        f"{record.id}: {name}",
    )
    return 0


def _remove(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    record = find_record(project, args.feature)
    context.apply(
        SetModuleDataCommand(
            project.id,
            MODULE_ID,
            write_catalogue(without_record(read_catalogue(project), record.id)),
        )
    )
    cleared = placements(project).get(record.id, [])
    for step in cleared:
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, clear()))
    note = f"{record.id}: {record.title} — removed"
    if cleared:
        note += " (" + ", ".join(repr(step.title) for step in cleared) + " is a plain step now)"
    context.report(
        {"project": project.id, "feature": record.id, "cleared": [step.id for step in cleared]},
        note,
    )
    return 0


def _set(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    project = context.library.project_of(step.id)
    current = read(step)
    if args.feature is None and current:
        # Already registered is success — state-setting verbs must survive batches.
        record = find_record(project, current)
        context.report(
            {"step": step.id, "feature": record.id},
            f"{step.title}: already realises {record.id} ({record.title})",
        )
        return 0
    if args.feature is not None and current == find_record(project, args.feature).id:
        context.report(
            {"step": step.id, "feature": current}, f"{step.title}: already realises {current}"
        )
        return 0
    record = _placed(context, project, step, args.feature or "")
    context.report(
        {"step": step.id, "feature": record.id},
        f"{step.title}: realises {record.id} ({record.title})",
    )
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if read(step) is None:
        # Already clear is success — state-clearing verbs must survive batches.
        context.report({"step": step.id, "feature": None}, f"{step.title}: not a feature")
        return 0
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, clear()))
    context.report(
        {"step": step.id, "feature": None},
        f"{step.title}: no longer a feature's instance (the feature stays in the catalogue)",
    )
    return 0
