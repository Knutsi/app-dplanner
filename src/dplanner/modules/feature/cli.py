"""``dplanner feature …`` — which steps are features, and the spec passages each was
read from.

A feature is a **step**: one a person would name and demo, with the work upstream of it
flowing into it. So there is no verb here that creates or removes one — ``step add
--feature`` is the door in (it carries ``--document``/``--quote``/``--page`` for a feature
read straight out of a spec) and ``step remove`` the door out, which is what keeps a
feature on the graph by construction. ``feature set`` and ``feature clear`` are the Type
toggle's headless half.

``feature cite`` adds a further passage — a feature is routinely described in two places
of a spec — and ``feature uncite`` takes one away.

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

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import find_project, find_step, project_arg, project_of_step, step_arg
from dplanner.core.anchors import Anchor
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.shelf import turn_off, turn_on
from dplanner.domain.store import FilesFor
from dplanner.modules.feature.aspect import (
    MODULE_ID,
    FeatureSource,
    cited_at,
    is_feature,
    passages_phrase,
    read,
    write,
)

# (files, project, [(document, quote, the digest it was read against)]) → an Anchor each.
type Anchoring = Callable[[FilesFor, Project, Sequence[tuple[str, str, str]]], list[Anchor]]

# What `reanchor` did with a passage, worded once for the text and the JSON.
STAMPED = "stamped"
ACCEPTED = "accepted"
DROPPED = "dropped"
KEPT = "kept"


def _no_key(_step: Step) -> str:
    return ""


def refs(cites: Sequence[FeatureSource]) -> list[tuple[str, str, str]]:
    return [(source.document, source.quote, source.digest) for source in cites]


def features_in(project: Project) -> list[Step]:
    """Every feature step, in project order — the catalogue, derived."""
    return [step for step in project.steps if is_feature(step)]


def commands(*, anchor: Anchoring, key_of: Callable[[Step], str] = _no_key) -> list[CliCommand]:
    """``key_of`` is the step's readable key (``F3``), handed in by the root so a feature
    row here names a step exactly as the canvas and every other listing do."""

    def judged(
        context: CliContext, project: Project, cites: Sequence[FeatureSource]
    ) -> list[Anchor]:
        return anchor(context.store.files, project, refs(cites))

    def feature_step(context: CliContext, args: Namespace) -> tuple[Project, Step]:
        """The step a verb names, refused unless it is a feature — the one lookup these
        verbs share, so they cannot disagree about what they act on."""
        step = find_step(context.library, args.step, context.current)
        if read(step) is None:
            raise CliError(
                f"{step.title!r} is not a feature — `dplanner feature set {step.title!r}` "
                "makes it one"
            )
        return context.library.project_of(step.id), step

    def row(context: CliContext, project: Project, step: Step) -> dict[str, object]:
        cites = read(step) or ()
        return _row(project, step, key_of, cites, judged(context, project, cites))

    def _cite(context: CliContext, args: Namespace) -> int:
        project, step = feature_step(context, args)
        cites = read(step) or ()
        if cited_at(cites, args.document, args.quote) is not None:
            context.report(
                row(context, project, step) | {"outcome": "unchanged"},
                f"{key_of(step)}: already cites that passage of {args.document}",
            )
            return 0
        cites, warning = _cited(context, project, cites, args, anchor)
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(cites)))
        context.report(
            row(context, project, step) | {"outcome": "cited"},
            f"{key_of(step)} {step.title}: cites {len(cites)} "
            f"passage{'s' if len(cites) != 1 else ''}" + warning,
        )
        return 0

    def _uncite(context: CliContext, args: Namespace) -> int:
        project, step = feature_step(context, args)
        cites = read(step) or ()
        if args.all:
            kept: tuple[FeatureSource, ...] = ()
        elif args.document is None:
            raise CliError("say which passage: --document D [--quote Q], or --all")
        else:
            index = cited_at(cites, args.document, args.quote) if args.quote else None
            kept = tuple(
                source
                for position, source in enumerate(cites)
                if source.document != args.document or (args.quote and position != index)
            )
        gone = len(cites) - len(kept)
        if gone:
            context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(kept)))
        context.report(
            row(context, project, step) | {"removed": gone},
            f"{key_of(step)}: {gone} passage{'s' if gone != 1 else ''} removed"
            if gone
            else f"{key_of(step)}: nothing to remove — it does not cite that",
        )
        return 0

    def _reanchor(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        if args.step is None and not args.all:
            raise CliError("name a feature step, or --all for every feature in the project")
        if args.all:
            chosen = features_in(project)
        else:
            chosen = [find_step(context.library, args.step, context.current)]
            if read(chosen[0]) is None:
                raise CliError(f"{chosen[0].title!r} is not a feature")
        rows: list[dict[str, object]] = []
        for step in chosen:
            cites = read(step) or ()
            kept: list[FeatureSource] = []
            for source, verdict in zip(cites, judged(context, project, cites), strict=True):
                action, still = _reanchored(source, verdict, args)
                if still is not None:
                    kept.append(still)
                rows.append(
                    {
                        "step": step.id,
                        "key": key_of(step),
                        "document": source.document,
                        "quote": source.quote,
                        "state": verdict.state,
                        "action": action,
                        **({"candidate": verdict.candidate} if verdict.candidate else {}),
                    }
                )
            if tuple(kept) != cites and not args.dry_run:
                context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(kept)))
        context.report(
            {"project": project.id, "passages": rows, "dry_run": bool(args.dry_run)},
            _reanchor_text(rows, args.dry_run),
        )
        return 0

    def _list(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        steps = features_in(project)
        if args.document is not None:
            steps = [
                step
                for step in steps
                if any(source.document == args.document for source in read(step) or ())
            ]
        lines = [
            f"{key_of(step):<4} {step.title}  — {passages_phrase(read(step) or ())}"
            for step in steps
        ]
        context.report(
            {"project": project.id, "features": [row(context, project, step) for step in steps]},
            "\n".join(lines)
            or "(no features yet — `dplanner step add … --feature`, or read one out of a spec)",
        )
        return 0

    def _show(context: CliContext, args: Namespace) -> int:
        project, step = feature_step(context, args)
        cites = read(step) or ()
        verdicts = judged(context, project, cites)
        lines = [f"{key_of(step)} {step.title}", passages_phrase(cites)]
        for source, verdict in zip(cites, verdicts, strict=True):
            page = f" p.{source.page}" if source.page is not None else ""
            state = "" if verdict.state == "anchored" else f"  [{verdict.state}]"
            lines.append(f"from {source.document}{page}{state}")
            lines += [f"  > {quoted}" for quoted in source.quote.splitlines()]
            if verdict.candidate:
                lines.append(f"  now reads: {verdict.candidate}")
        lines += ["", f"what flows into it: `dplanner scope show {step.title!r}`"]
        context.report(_row(project, step, key_of, cites, verdicts), "\n".join(lines))
        return 0

    def _set(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        if read(step) is not None:
            # Already a feature is success — state-setting verbs must survive batches.
            context.report({"step": step.id, "feature": True}, f"{step.title}: already a feature")
            return 0
        context.apply(turn_on(step, MODULE_ID, fresh=write(), label="Mark as Feature"))
        context.report({"step": step.id, "feature": True}, f"{step.title}: is a feature")
        return 0

    def _clear(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        if read(step) is None:
            # Already clear is success — state-clearing verbs must survive batches.
            context.report({"step": step.id, "feature": False}, f"{step.title}: not a feature")
            return 0
        context.apply(turn_off(step.id, MODULE_ID, label="Clear Feature"))
        context.report(
            {"step": step.id, "feature": False},
            f"{step.title}: no longer a feature (its passages are shelved)",
        )
        return 0

    return [
        CliCommand(
            path=("feature", "list"),
            summary="A project's features — the steps that are one — and what each was read from.",
            configure=_configure_list,
            run=_list,
            examples=(
                "dplanner feature list discovery",
                "dplanner feature list discovery --document auth-spec --json",
            ),
        ),
        CliCommand(
            path=("feature", "show"),
            summary="One feature in full: the spec passages it was read from and whether "
            "each still anchors.",
            configure=step_arg,
            run=_show,
            examples=("dplanner feature show 'Bulk import'",),
        ),
        CliCommand(
            path=("feature", "cite"),
            summary="Add a spec passage a feature was read from — a feature is often "
            "described in more than one place; the quote is anchored and stamped.",
            configure=_configure_cite,
            run=_cite,
            examples=(
                "dplanner feature cite 'Bulk import' --document auth-spec"
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
                "dplanner feature uncite 'Bulk import' --document auth-spec"
                " --quote 'Imports MUST…'",
                "dplanner feature uncite 'Bulk import' --all",
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
                "dplanner feature reanchor discovery 'Bulk import' --accept-drift",
            ),
        ),
        CliCommand(
            path=("feature", "set"),
            summary="Make a step a feature: the work upstream of it flows into it.",
            configure=step_arg,
            run=_set,
            examples=("dplanner feature set 'Bulk import'",),
            edits_graph=project_of_step,
        ),
        CliCommand(
            path=("feature", "clear"),
            summary="A step is no longer a feature; what it cited is shelved and comes "
            "back if it is made one again.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner feature clear 'Bulk import'",),
            edits_graph=project_of_step,
        ),
    ]


def step_author(*, anchor: Anchoring) -> StepAuthor:
    """``step add``'s feature flags: the step is born a feature, optionally read straight
    out of a spec passage.

    The passage arguments live here rather than on a verb of this module's own, because
    *authoring a step is one verb, many modules*: a feature is created by creating its
    step, and what it was read from is one of that step's facts.
    """

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--feature",
            action="store_true",
            help="this step is a feature: the work upstream of it flows into it",
        )
        parser.add_argument(
            "--document", help="the spec document this feature was read from (needs --feature)"
        )
        parser.add_argument("--quote", default="", help="the passage it was read from")
        parser.add_argument(
            "--page", type=int, help="the page it sits on (default: where the quote is found)"
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="refuse when the quote is not found in the document, instead of warning",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if not args.feature:
            if args.document is not None:
                raise CliError("--document needs --feature: only a feature cites a passage")
            return None
        project = context.library.project_of(step.id)
        cites, warning = _cited(context, project, (), args, anchor)
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(cites)))
        note = "feature" + (f" · {passages_phrase(cites)}" if cites else "")
        return StepAuthored({"feature": True}, note + warning)

    return StepAuthor(configure, author)


def lint_checks(*, anchor: Anchoring, key_of: Callable[[Step], str] = _no_key) -> list[LintCheck]:
    def passages(_product: Library, project: Project, files: FilesFor) -> list[LintFinding]:
        """Every passage judged again — never a stored answer, because `spec import`
        replaces a document with no window running to notice. Lost, drifted and behind
        each name the verb that resolves them; a passage whose document is gone is
        nobody's finding (there is nothing to check it against)."""
        findings = []
        for step in features_in(project):
            cites = read(step) or ()
            verdicts = anchor(files, project, refs(cites))
            for source, verdict in zip(cites, verdicts, strict=True):
                finding = _passage_finding(step, key_of(step), source, verdict)
                if finding is not None:
                    findings.append(finding)
        return findings

    return [passages]


def _passage_finding(
    step: Step, key: str, source: FeatureSource, verdict: Anchor
) -> LintFinding | None:
    reanchor = f"`dplanner feature reanchor {step.title!r}"
    if verdict.state == "lost":
        check, message = (
            "feature.quote-unanchored",
            f"its quote no longer anchors in {source.document} — re-read the document and "
            f"`dplanner feature cite {step.title!r} --document {source.document} --quote …` "
            f"the passage as it reads now, or {reanchor} --drop-lost` to forget it",
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
    subject = f"{key} {step.title}".strip()
    return LintFinding(check=check, subject_id=step.id, subject=subject, message=message)


# -- parsers -----------------------------------------------------------------------------------


def _configure_list(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--document", help="only features read from this spec document")


def _configure_cite(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--document", required=True, help="the spec document it was read from")
    parser.add_argument("--quote", default="", help="the passage it was read from")
    parser.add_argument(
        "--page", type=int, help="the page it sits on (default: where the quote is found)"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="refuse when the quote is not found in the document, instead of warning",
    )


def _configure_uncite(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--document", help="the document the passage is in")
    parser.add_argument(
        "--quote", default="", help="the passage (default: every passage of the document)"
    )
    parser.add_argument("--all", action="store_true", help="forget every passage")


def _configure_reanchor(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("step", nargs="?", help="one feature step (default: --all)")
    parser.add_argument("--all", action="store_true", help="every feature in the project")
    parser.add_argument(
        "--accept-drift", action="store_true", help="replace a drifted quote with the new wording"
    )
    parser.add_argument("--drop-lost", action="store_true", help="forget a passage that is gone")
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would change; write nothing"
    )


# -- shared halves -----------------------------------------------------------------------------


def _cited(
    context: CliContext,
    project: Project,
    cites: Sequence[FeatureSource],
    args: Namespace,
    anchor: Anchoring,
) -> tuple[tuple[FeatureSource, ...], str]:
    """``cites`` with the passage ``args`` name appended, stamped with the document as it
    is now, and the warning line to print, if any. Shared by ``cite`` and ``step add``.

    Only a definite miss refuses under ``--strict``: a document that cannot be read is
    "nothing to check", and strictness must not punish the unknowable. A quote can recur;
    ``--page`` naming any occurrence is disambiguation, not a miss.
    """
    if args.document is None:
        if args.quote or args.page is not None:
            raise CliError("--quote and --page need --document: which spec was it read from?")
        return tuple(cites), ""
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
    return (*cites, source), warning


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


def _reanchor_text(rows: Sequence[dict[str, object]], dry_run: bool) -> str:
    if not rows:
        return "(no passages cited — `dplanner feature cite` reads a feature out of a spec)"
    lines = []
    for entry in rows:
        note = f"{entry['key']:<4} {entry['document']}  {entry['state']}  {entry['action']}"
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


def _row(
    project: Project,
    step: Step,
    key_of: Callable[[Step], str],
    cites: Sequence[FeatureSource],
    verdicts: Sequence[Anchor],
) -> dict[str, object]:
    return {
        "project": project.id,
        "step": {"id": step.id, "key": key_of(step), "title": step.title},
        "cites": [
            {
                "document": source.document,
                "quote": source.quote,
                "page": source.page,
                "digest": source.digest,
                "anchoring": verdict.state,
                **({"candidate": verdict.candidate} if verdict.candidate else {}),
            }
            for source, verdict in zip(cites, verdicts, strict=True)
        ],
    }
