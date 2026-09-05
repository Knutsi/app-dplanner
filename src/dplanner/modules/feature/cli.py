"""``dplanner feature …`` — the project's catalogue of features, which step realises
each, and the spec passages each was read from.

A feature is read out of a spec (``feature add --document … --quote …``: the quote is
anchored in the document) or added by hand, and lives in the catalogue whether or not it
is on the graph yet. ``feature cite`` adds a further passage — a feature is routinely
described in two places of a spec — and ``feature uncite`` takes one away. ``feature set``
makes a step the instance of one, or mints a record for a step that is a feature nobody
catalogued, and ``step add --feature`` does the same for a step being born. One record has
one instance; a second is refused, because a feature is implemented once.

**The spec changes under its citations, and ``feature reanchor`` is how they catch up.**
Every passage is judged again on every read — anchored, behind, drifted or lost
(``core/anchors.py``) — and ``reanchor`` re-stamps the ones still there, takes a drifted
one's new wording when told to, and drops a lost one when told to. Nothing here decides
what a passage *is*: the anchoring arrives as ``anchor`` from the spec module, handed
across by the composition root, so this file never learns how a document is stored.

What a feature *gathers* is not here: that is ``dplanner scope show``, one verb over every
kind of collector, because a check, a feature and a milestone are one derivation asked
three ways.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
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
from dplanner.core.anchors import Anchor
from dplanner.domain.assets import attach
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.shelf import turn_off
from dplanner.domain.store import FilesFor
from dplanner.modules.feature.aspect import MODULE_ID, read, write
from dplanner.modules.feature.catalogue import (
    FeatureRecord,
    FeatureSource,
    cited_at,
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

# (files, project, [(document, quote, the digest it was read against)]) → an Anchor each.
type Anchoring = Callable[[FilesFor, Project, Sequence[tuple[str, str, str]]], list[Anchor]]

# What `reanchor` did with a passage, worded once for the text and the JSON.
STAMPED = "stamped"
ACCEPTED = "accepted"
DROPPED = "dropped"
KEPT = "kept"


def refs(record: FeatureRecord) -> list[tuple[str, str, str]]:
    return [(source.document, source.quote, source.digest) for source in record.sources]


def commands(*, anchor: Anchoring) -> list[CliCommand]:
    def judged(context: CliContext, project: Project, record: FeatureRecord) -> list[Anchor]:
        return anchor(context.store.files, project, refs(record))

    def row(context: CliContext, project: Project, record: FeatureRecord) -> dict[str, object]:
        return _row(context, project, record, judged(context, project, record))

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
        record, warning = _cited(context, project, record, args, anchor)
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
        context.report(row(context, project, record) | {"outcome": "added"}, note + warning)
        return 0

    def _edit(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        record = find_record(project, args.feature)
        if args.title:
            record = replace(record, title=args.title)
        if args.describe_file:
            record = replace(record, description=body_from(args.describe_file))
        _save(context, project, record)
        context.report(
            row(context, project, record) | {"outcome": "updated"},
            f"{record.id}: {record.title} — updated",
        )
        return 0

    def _cite(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        record = find_record(project, args.feature)
        if cited_at(record, args.document, args.quote) is not None:
            context.report(
                row(context, project, record) | {"outcome": "unchanged"},
                f"{record.id}: already cites that passage of {args.document}",
            )
            return 0
        record, warning = _cited(context, project, record, args, anchor)
        _save(context, project, record)
        context.report(
            row(context, project, record) | {"outcome": "cited"},
            f"{record.id}: {record.title} — cites {len(record.sources)} "
            f"passage{'s' if len(record.sources) != 1 else ''}" + warning,
        )
        return 0

    def _uncite(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        record = find_record(project, args.feature)
        if args.all:
            kept: tuple[FeatureSource, ...] = ()
        elif args.document is None:
            raise CliError("say which passage: --document D [--quote Q], or --all")
        else:
            index = cited_at(record, args.document, args.quote) if args.quote else None
            kept = tuple(
                source
                for position, source in enumerate(record.sources)
                if source.document != args.document or (args.quote and position != index)
            )
        gone = len(record.sources) - len(kept)
        if gone:
            record = replace(record, sources=kept)
            _save(context, project, record)
        context.report(
            row(context, project, record) | {"removed": gone},
            f"{record.id}: {gone} passage{'s' if gone != 1 else ''} removed"
            if gone
            else f"{record.id}: nothing to remove — it does not cite that",
        )
        return 0

    def _reanchor(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        if args.feature is None and not args.all:
            raise CliError("name a feature, or --all for every feature in the project")
        records = read_catalogue(project)
        chosen = records if args.all else [find_record(project, args.feature)]
        rows: list[dict[str, object]] = []
        updated: list[FeatureRecord] = []
        for record in chosen:
            sources: list[FeatureSource] = []
            for source, verdict in zip(
                record.sources, judged(context, project, record), strict=True
            ):
                action, kept = _reanchored(source, verdict, args)
                if kept is not None:
                    sources.append(kept)
                rows.append(
                    {
                        "feature": record.id,
                        "document": source.document,
                        "quote": source.quote,
                        "state": verdict.state,
                        "action": action,
                        **({"candidate": verdict.candidate} if verdict.candidate else {}),
                    }
                )
            if tuple(sources) != record.sources:
                updated.append(replace(record, sources=tuple(sources)))
        if updated and not args.dry_run:
            for record in updated:
                records = with_record(records, record)
            context.apply(SetModuleDataCommand(project.id, MODULE_ID, write_catalogue(records)))
        context.report(
            {"project": project.id, "passages": rows, "dry_run": bool(args.dry_run)},
            _reanchor_text(rows, project, args.dry_run),
        )
        return 0

    def _list(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        records = read_catalogue(project)
        if args.document is not None:
            records = [
                record
                for record in records
                if any(source.document == args.document for source in record.sources)
            ]
        rows = [row(context, project, record) for record in records]
        lines = [
            f"{record.id:<4} {record.title}  — "
            f"{summary_line(record, instance_of(project, record.id))}"
            for record in records
        ]
        for step in unregistered(project):
            lines.append(
                f"     {step.title}  — feature step with no record; `dplanner feature set`"
            )
        context.report(
            {"project": project.id, "features": rows},
            "\n".join(lines)
            or "(no features yet — `dplanner feature add`, or read them out of a spec)",
        )
        return 0

    def _show(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        record = find_record(project, args.feature)
        verdicts = judged(context, project, record)
        instance = instance_of(project, record.id)
        lines = [f"{record.id}: {record.title}", summary_line(record, instance)]
        for source, verdict in zip(record.sources, verdicts, strict=True):
            page = f" p.{source.page}" if source.page is not None else ""
            state = "" if verdict.state == "anchored" else f"  [{verdict.state}]"
            lines.append(f"from {source.document}{page}{state}")
            lines += [f"  > {quoted}" for quoted in source.quote.splitlines()]
            if verdict.candidate:
                lines.append(f"  now reads: {verdict.candidate}")
        if record.description:
            lines += ["", record.description.rstrip("\n")]
        for path in image_paths(context.store.files, project.id, record):
            lines.append(f"image: {path}")
        if instance is not None:
            lines += ["", f"what flows into it: `dplanner scope show {instance.title!r}`"]
        context.report(_row(context, project, record, verdicts), "\n".join(lines))
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
            summary="One feature in full: its description, the spec passages it was read "
            "from and whether each still anchors, its images, and the step that realises it.",
            configure=_configure_feature,
            run=_show,
            examples=("dplanner feature show discovery f1",),
        ),
        CliCommand(
            path=("feature", "add"),
            summary="Add a feature to a project's catalogue — read from a spec passage "
            "(the quote is anchored in the document) or by hand.",
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
            summary="Change a feature's title or description.",
            configure=_configure_edit,
            run=_edit,
            examples=("dplanner feature edit discovery f1 --title 'Bulk CSV import'",),
        ),
        CliCommand(
            path=("feature", "cite"),
            summary="Add a spec passage a feature was read from — a feature is often "
            "described in more than one place; the quote is anchored and stamped.",
            configure=_configure_cite,
            run=_cite,
            examples=(
                "dplanner feature cite discovery f1 --document auth-spec"
                " --quote 'Imports MUST report every rejected row' --page 6",
            ),
        ),
        CliCommand(
            path=("feature", "uncite"),
            summary="Forget a passage a feature was read from — one, every passage of a "
            "document, or all of them.",
            configure=_configure_uncite,
            run=_uncite,
            examples=(
                "dplanner feature uncite discovery f1 --document auth-spec --quote 'Imports MUST…'",
                "dplanner feature uncite discovery f1 --all",
            ),
        ),
        CliCommand(
            path=("feature", "reanchor"),
            summary="After the spec changed: re-stamp every passage still there, take a "
            "reworded one's new text (--accept-drift), drop a vanished one (--drop-lost).",
            configure=_configure_reanchor,
            run=_reanchor,
            examples=(
                "dplanner feature reanchor discovery --all --dry-run",
                "dplanner feature reanchor discovery f1 --accept-drift",
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


def lint_checks(*, anchor: Anchoring) -> list[LintCheck]:
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

    def passages(_product: Library, project: Project, files: FilesFor) -> list[LintFinding]:
        """Every passage judged again — never a stored answer, because `spec import`
        replaces a document with no window running to notice. Lost, drifted and behind
        each name the verb that resolves them; a passage whose document is gone is
        nobody's finding (there is nothing to check it against)."""
        findings = []
        for record in read_catalogue(project):
            verdicts = anchor(files, project, refs(record))
            for source, verdict in zip(record.sources, verdicts, strict=True):
                finding = _passage_finding(project, record, source, verdict)
                if finding is not None:
                    findings.append(finding)
        return findings

    return [catalogue_findings, passages]


def _passage_finding(
    project: Project, record: FeatureRecord, source: FeatureSource, verdict: Anchor
) -> LintFinding | None:
    reanchor = f"`dplanner feature reanchor '{project.title}' {record.id}"
    if verdict.state == "lost":
        check, message = (
            "feature.quote-unanchored",
            f"its quote no longer anchors in {source.document} — re-read the document and "
            f"`dplanner feature cite '{project.title}' {record.id} --document "
            f"{source.document} --quote …` the passage as it reads now, or {reanchor} "
            "--drop-lost` to forget it",
        )
    elif verdict.state == "drifted":
        check, message = (
            "feature.quote-drifted",
            f"its quote in {source.document} now reads “{verdict.candidate}” "
            f"({verdict.ratio:.0%} alike) — {reanchor} --accept-drift` takes the new wording",
        )
    elif verdict.state == "behind":
        check, message = (
            "feature.spec-changed",
            f"{source.document} changed around its quote since it was read — re-read the "
            f"passage, then {reanchor}` to accept",
        )
    else:
        return None
    return LintFinding(check=check, subject_id=record.id, subject=record.title, message=message)


# -- parsers -----------------------------------------------------------------------------------


def _configure_list(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--document", help="only features read from this spec document")


def _configure_feature(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("feature", help="a feature id from `feature list`, or part of its title")


def _passage_args(parser: ArgumentParser, *, required: bool) -> None:
    parser.add_argument("--document", required=required, help="the spec document it was read from")
    parser.add_argument("--quote", default="", help="the passage it was read from")
    parser.add_argument(
        "--page", type=int, help="the page it sits on (default: where the quote is found)"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="refuse when the quote is not found in the document, instead of warning",
    )


def _describe_arg(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--describe-file", metavar="FILE", help="a markdown description, or - for stdin"
    )


def _configure_add(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("title", help="what the feature is called")
    parser.add_argument("--id", help="feature id (default: the next free fN)")
    _passage_args(parser, required=False)
    _describe_arg(parser)
    parser.add_argument(
        "--image", nargs="+", metavar="FILE", help="images showing the feature, copied in"
    )


def _configure_edit(parser: ArgumentParser) -> None:
    _configure_feature(parser)
    parser.add_argument("--title", help="the new title")
    _describe_arg(parser)


def _configure_cite(parser: ArgumentParser) -> None:
    _configure_feature(parser)
    _passage_args(parser, required=True)


def _configure_uncite(parser: ArgumentParser) -> None:
    _configure_feature(parser)
    parser.add_argument("--document", help="the document the passage is in")
    parser.add_argument(
        "--quote", default="", help="the passage (default: every passage of the document)"
    )
    parser.add_argument("--all", action="store_true", help="forget every passage")


def _configure_reanchor(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("feature", nargs="?", help="one feature (default: --all)")
    parser.add_argument("--all", action="store_true", help="every feature in the project")
    parser.add_argument(
        "--accept-drift", action="store_true", help="replace a drifted quote with the new wording"
    )
    parser.add_argument("--drop-lost", action="store_true", help="forget a passage that is gone")
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would change; write nothing"
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


def _cited(
    context: CliContext,
    project: Project,
    record: FeatureRecord,
    args: Namespace,
    anchor: Anchoring,
) -> tuple[FeatureRecord, str]:
    """``record`` with the passage ``args`` name appended, stamped with the document as it
    is now, and the warning line to print, if any. Shared by ``add`` and ``cite``.

    Only a definite miss refuses under ``--strict``: a document that cannot be read is
    "nothing to check", and strictness must not punish the unknowable. A quote can recur;
    ``--page`` naming any occurrence is disambiguation, not a miss.
    """
    if args.document is None:
        if args.quote or args.page is not None:
            raise CliError("--quote and --page need --document: which spec was it read from?")
        return record, ""
    [verdict] = anchor(context.store.files, project, [(args.document, args.quote, "")])
    missed = verdict.state in ("drifted", "lost")
    if args.strict and missed:
        raise CliError(
            f"--strict: the quote was not found in {args.document} — check the wording "
            "against `dplanner spec show`, or drop --strict (PDF extraction can mangle text)"
        )
    page = args.page if args.page is not None else verdict.page
    warning = ""
    if args.quote and missed:
        warning = "\nwarning: the quote was not found in the document — check it anchors"
        if verdict.candidate:
            warning += f"\n         nearest passage: {verdict.candidate}"
    elif args.page is not None and verdict.pages and args.page not in verdict.pages:
        anchored = ", ".join(str(number) for number in verdict.pages)
        warning = (
            f"\nwarning: the quote was not found on page {args.page} — it anchors on {anchored}"
        )
    source = FeatureSource(
        document=args.document, quote=args.quote, page=page, digest=verdict.digest
    )
    return replace(record, sources=(*record.sources, source)), warning


def _reanchored(
    source: FeatureSource, verdict: Anchor, args: Namespace
) -> tuple[str, FeatureSource | None]:
    """What `reanchor` does with one passage: the action word, and the passage as kept
    (None to drop it)."""
    if verdict.state in ("anchored", "behind"):
        if source.digest == verdict.digest:
            return KEPT, source
        return STAMPED, replace(source, digest=verdict.digest)
    if verdict.state == "drifted" and args.accept_drift:
        return ACCEPTED, replace(
            source, quote=verdict.candidate, page=verdict.page, digest=verdict.digest
        )
    if verdict.state == "lost" and args.drop_lost:
        return DROPPED, None
    return KEPT, source


def _reanchor_text(rows: Sequence[dict[str, object]], project: Project, dry_run: bool) -> str:
    if not rows:
        return "(no passages cited — `dplanner feature cite` reads a feature out of a spec)"
    lines = []
    for entry in rows:
        note = f"{entry['feature']:<4} {entry['document']}  {entry['state']}  {entry['action']}"
        if entry.get("candidate"):
            note += f"\n     now reads: {entry['candidate']}"
        lines.append(note)
    left = {
        state: sum(1 for entry in rows if entry["state"] == state and entry["action"] == KEPT)
        for state in ("drifted", "lost", "missing")
    }
    summary = []
    if left["drifted"]:
        summary.append(f"{left['drifted']} drifted — `--accept-drift` takes the new wording")
    if left["lost"]:
        summary.append(f"{left['lost']} lost — `--drop-lost` forgets them, or `feature cite` anew")
    if left["missing"]:
        summary.append(f"{left['missing']} in a document that is not in the index")
    if dry_run:
        summary.append("dry run: nothing written")
    return "\n".join([*lines, *summary])


def _save(context: CliContext, project: Project, record: FeatureRecord) -> None:
    context.apply(
        SetModuleDataCommand(
            project.id, MODULE_ID, write_catalogue(with_record(read_catalogue(project), record))
        )
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


def _row(
    context: CliContext, project: Project, record: FeatureRecord, verdicts: Sequence[Anchor]
) -> dict[str, object]:
    instance = instance_of(project, record.id)
    return {
        "project": project.id,
        "feature": record.id,
        "title": record.title,
        "description": record.description,
        "sources": [
            {
                "document": source.document,
                "quote": source.quote,
                "page": source.page,
                "digest": source.digest,
                "anchoring": verdict.state,
                **({"candidate": verdict.candidate} if verdict.candidate else {}),
            }
            for source, verdict in zip(record.sources, verdicts, strict=True)
        ],
        "images": list(image_paths(context.store.files, project.id, record)),
        "step": {"id": instance.id, "title": instance.title} if instance is not None else None,
    }


# -- verbs -------------------------------------------------------------------------------------


def _attach(context: CliContext, args: Namespace) -> int:
    project = find_project(context.library, args.project)
    record = find_record(project, args.feature)
    name = _attached(context, project, args.file)
    if name not in record.images:
        record = replace(record, images=(*record.images, name))
        _save(context, project, record)
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
        context.apply(turn_off(step.id, MODULE_ID, label="Remove Feature"))
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
    context.apply(turn_off(step.id, MODULE_ID, label="Remove Feature"))
    context.report(
        {"step": step.id, "feature": None},
        f"{step.title}: no longer a feature's instance (the feature stays in the catalogue)",
    )
    return 0
