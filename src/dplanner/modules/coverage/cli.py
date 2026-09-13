"""``dplanner coverage …`` — the spec, and what became of it.

Three readings of one derived picture (:mod:`.trace`): ``show`` walks it from the
documents down to the tests and docs; ``spec`` reads one document paragraph by paragraph
and says which features each was read into — ``--uncovered`` is the agent's inbox; and
``review`` lists what needs a person's or an agent's attention after the spec changed —
every passage no longer simply *anchored*, every feature that cites nothing, every
document nobody cites — each with the verb that resolves it.

Nothing here decides what a passage or a feature is: the picture arrives built, through
``trace_of`` from the composition root, so this file imports no other module.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_project, project_arg
from dplanner.domain.model import Library, Project
from dplanner.domain.store import FilesFor
from dplanner.modules.coverage.trace import (
    FEATURES,
    MILESTONES,
    NO_MILESTONE,
    SPEC,
    DocumentCoverage,
    Item,
    Trace,
)

type TraceOf = Callable[[Library, Project, FilesFor], Trace]

EXCERPT = 72  # How much of a paragraph a report line shows.

# What resolves each finding — one place, so the text and the JSON agree.
_ADVICE = {
    "behind": "re-read the passage, then `dplanner feature reanchor {project} {feature}`",
    "drifted": "`dplanner feature reanchor {project} {feature} --accept-drift` takes the new "
    "wording",
    "lost": "`dplanner feature cite {feature} --document {document} --quote …` the "
    "passage as it reads now, or `feature reanchor {project} {feature} --drop-lost`",
    "missing": "`dplanner spec import` the document again, or "
    "`feature uncite {feature} --document {document}`",
    "unsourced": "`dplanner feature cite {feature} --document <D> --quote …` — "
    "`dplanner coverage spec {project} <D> --uncovered` shows what is unclaimed",
    "uncited": "`dplanner coverage spec {project} {document} --uncovered`, then "
    "`dplanner step add {project} <name> --feature --document {document} --quote …`",
}


def commands(*, trace_of: TraceOf) -> list[CliCommand]:
    def _show(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        trace = trace_of(context.library, project, context.store.files)
        wanted = None
        if args.feature:
            wanted = _feature_id(trace, args.feature)
        data = _trace_json(trace, document=args.document, feature=wanted)
        context.report(data, _render_show(trace, document=args.document, feature=wanted))
        return 0

    def _spec(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        trace = trace_of(context.library, project, context.store.files)
        covered = next((doc for doc in trace.documents if doc.name == args.document), None)
        if covered is None:
            names = ", ".join(doc.name for doc in trace.documents) or "none"
            raise CliError(f"no spec document named {args.document!r} — documents: {names}")
        if not covered.readable:
            raise CliError(f"{covered.name}: the document cannot be read")
        shown = [
            block
            for block in covered.blocks
            if not block.is_heading and (not args.uncovered or not block.features)
        ]
        context.report(
            {
                "project": project.id,
                "document": covered.name,
                "paragraphs": covered.paragraphs,
                "cited": covered.cited,
                "blocks": [
                    {
                        "start": block.start,
                        "end": block.end,
                        "heading": block.heading,
                        "page": block.page,
                        "text": block.text,
                        "features": list(block.features),
                    }
                    for block in shown
                ],
            },
            _render_spec(covered, shown, uncovered_only=bool(args.uncovered)),
        )
        return 0

    def _review(context: CliContext, args: Namespace) -> int:
        project = find_project(context.library, args.project)
        trace = trace_of(context.library, project, context.store.files)
        rows = _review_rows(trace, project)
        context.report(
            {"project": project.id, "findings": rows, "count": len(rows)},
            "\n".join(f"{row['subject']:<12} {row['what']}\n    {row['advice']}" for row in rows)
            or "every passage anchors, every feature cites a passage, every document is read",
        )
        return 0

    return [
        CliCommand(
            path=("coverage", "show"),
            summary="The whole trace: each spec document's passages, the features read "
            "from them, the milestones gathering those, and their tests and docs.",
            configure=_configure_show,
            run=_show,
            examples=(
                "dplanner coverage show discovery",
                "dplanner coverage show discovery --feature f1",
                "dplanner coverage show discovery --document auth-spec --json",
            ),
        ),
        CliCommand(
            path=("coverage", "spec"),
            summary="One document paragraph by paragraph, with the features each was read "
            "into — --uncovered lists what no feature claims yet.",
            configure=_configure_spec,
            run=_spec,
            examples=(
                "dplanner coverage spec discovery auth-spec --uncovered",
                "dplanner coverage spec discovery auth-spec --json",
            ),
        ),
        CliCommand(
            path=("coverage", "review"),
            summary="What needs attention after the spec changed: passages no longer "
            "anchored, features citing nothing, documents nobody cites — each with its fix.",
            configure=project_arg,
            run=_review,
            examples=("dplanner coverage review discovery",),
        ),
    ]


# -- parsers -----------------------------------------------------------------------------------


def _configure_show(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("--document", help="only this spec document")
    parser.add_argument("--feature", help="only this feature (an id, or part of its title)")


def _configure_spec(parser: ArgumentParser) -> None:
    project_arg(parser)
    parser.add_argument("document", help="a spec document's name")
    parser.add_argument(
        "--uncovered", action="store_true", help="only the paragraphs no feature was read from"
    )


# -- shapes ------------------------------------------------------------------------------------


def _feature_id(trace: Trace, needle: str) -> str:
    items = trace.column(FEATURES)
    for item in items:
        if item.id == f"feature:{needle}":
            return needle
    lowered = needle.lower()
    found = [item for item in items if lowered in item.title.lower()]
    if len(found) == 1:
        return found[0].id.removeprefix("feature:")
    if not found:
        raise CliError(f"no feature {needle!r} — see `dplanner feature list`")
    listed = ", ".join(f"{item.id.removeprefix('feature:')} ({item.title})" for item in found)
    raise CliError(f"{needle!r} matches several features: {listed}")


def _item_json(item: Item) -> dict[str, object]:
    return {
        "id": item.id,
        "column": item.column,
        "title": item.title,
        "detail": item.detail,
        "state": item.state,
        "features": sorted(item.features),
        "target": list(item.target),
    }


def _trace_json(trace: Trace, *, document: str | None, feature: str | None) -> dict[str, object]:
    keep = _kept(trace, document=document, feature=feature)
    return {
        "items": [_item_json(item) for item in trace.items if item.id in keep],
        "links": [
            {"source": link.source, "target": link.target, "features": sorted(link.features)}
            for link in trace.links
            if link.source in keep and link.target in keep
        ],
        "documents": [
            {
                "name": doc.name,
                "kind": doc.kind,
                "readable": doc.readable,
                "paragraphs": doc.paragraphs,
                "cited": doc.cited,
                "review": doc.review,
            }
            for doc in trace.documents
            if document is None or doc.name == document
        ],
        "unsourced": [{"id": f.id, "title": f.title} for f in trace.unsourced],
    }


def _kept(trace: Trace, *, document: str | None, feature: str | None) -> set[str]:
    keep = {item.id for item in trace.items}
    if feature is not None:
        keep &= trace.path(f"feature:{feature}").items
    if document is not None:
        docs = {
            item.id
            for item in trace.column(SPEC)
            if item.id == f"doc:{document}" or item.id.startswith(f"passage:{document}:")
        }
        tokens: set[str] = set()
        for item in trace.items:
            if item.id in docs:
                tokens |= item.features
        keep &= docs | {item.id for item in trace.items if item.features & tokens}
    return keep


def _render_show(trace: Trace, *, document: str | None, feature: str | None) -> str:
    keep = _kept(trace, document=document, feature=feature)
    by_id = {item.id: item for item in trace.items}
    downstream: dict[str, list[str]] = {}
    for link in trace.links:
        downstream.setdefault(link.source, []).append(link.target)
    lines: list[str] = []
    seen_features: set[str] = set()

    def mark(item: Item) -> str:
        return f"  [{item.state}]" if item.state and item.state not in ("anchored",) else ""

    def feature_lines(fid: str, indent: str) -> None:
        # A feature is named by its step's title and keyed by its step's id, which is a
        # uuid nobody reads: the title is the name, and the id is what `--json` carries.
        item = by_id[f"feature:{fid}"]
        note = f"  ({item.detail})" if item.detail else ""
        lines.append(f"{indent}{item.title}{note}")
        seen_features.add(fid)
        for target in downstream.get(item.id, ()):
            if target not in keep:
                continue
            holder = by_id[target]
            lines.append(
                f"{indent}  ↳ {holder.title}" + (f" ({holder.detail})" if holder.detail else "")
            )
            for outcome in downstream.get(holder.id, ()):
                if outcome in keep and fid in by_id[outcome].features:
                    out = by_id[outcome]
                    what = "docs" if out.id.startswith("docs:") else out.detail.split(" · ")[0]
                    lines.append(f"{indent}      {what:<6} {out.title}{mark(out)}")

    for doc in trace.column(SPEC):
        if doc.id not in keep or not doc.id.startswith("doc:"):
            continue
        lines.append(f"{doc.title}: {doc.detail}")
        for passage in trace.column(SPEC):
            if passage.id not in keep or not passage.id.startswith(f"passage:{doc.title}:"):
                continue
            where = f" {passage.detail}" if passage.detail else ""
            lines.append(f'  "{passage.title}"{where}{mark(passage)}')
            for fid in sorted(passage.features):
                if f"feature:{fid}" in keep:
                    feature_lines(fid, "    → ")
    rest = [
        item
        for item in trace.column(FEATURES)
        if item.id in keep and item.id.removeprefix("feature:") not in seen_features
    ]
    if rest:
        lines.append("Features citing no passage:")
        for item in rest:
            feature_lines(item.id.removeprefix("feature:"), "  ")
    direct = [
        (holder, out)
        for holder in trace.column(MILESTONES)
        if holder.id in keep and holder.id != NO_MILESTONE
        for target in downstream.get(holder.id, ())
        if target in keep and (out := by_id[target]).features == {holder.id}
    ]
    if direct:
        lines.append("Held directly by a milestone:")
        for holder, out in direct:
            what = "docs" if out.id.startswith("docs:") else out.detail.split(" · ")[0]
            lines.append(f"  {holder.title}: {what} {out.title}{mark(out)}")
    return (
        "\n".join(lines)
        or "(nothing to trace — `dplanner spec import` a document and read features out of it)"
    )


def _render_spec(
    covered: DocumentCoverage, shown: Sequence[object], *, uncovered_only: bool
) -> str:
    lines = []
    for block in covered.blocks:
        if block.is_heading or block not in shown:
            continue
        where = " > ".join(part for part in (block.heading,) if part)
        page = f" p.{block.page}" if block.page is not None else ""
        cited = " ".join(block.features) if block.features else "-"
        excerpt = " ".join(block.text.split())
        if len(excerpt) > EXCERPT:
            excerpt = excerpt[: EXCERPT - 1] + "…"
        lines.append(f"[{cited}]  {where}{page}\n    {excerpt}")
    tail = f"{covered.cited} of {covered.paragraphs} paragraphs cited"
    if uncovered_only:
        tail = f"{covered.paragraphs - covered.cited} uncited — {tail}"
    return "\n".join([*lines, tail])


def _named(trace: Trace, feature_id: str) -> str:
    """A feature as a person would type it: the step's title, which `find_step` resolves.

    The trace keys a feature by its step's id, and an id nobody can type is no remedy.
    """
    item = trace.item(f"feature:{feature_id}")
    return repr(item.title if item is not None else feature_id)


def _review_rows(trace: Trace, project: Project) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    name = repr(project.title)
    for item in trace.column(SPEC):
        if not item.id.startswith("passage:") or item.state == "anchored":
            continue
        document = item.id.split(":", 2)[1]
        for fid in sorted(item.features):
            rows.append(
                {
                    "kind": item.state,
                    "subject": fid,
                    "document": document,
                    "what": f'{item.state}: "{item.title}" in {document}',
                    "advice": _ADVICE[item.state].format(
                        project=name, feature=_named(trace, fid), document=document
                    ),
                }
            )
    for feature in trace.unsourced:
        rows.append(
            {
                "kind": "unsourced",
                "subject": feature.id,
                "document": "",
                "what": f"unsourced: {feature.title} cites no spec passage",
                "advice": _ADVICE["unsourced"].format(project=name, feature=repr(feature.title)),
            }
        )
    for doc in trace.documents:
        if doc.readable and doc.cited == 0 and doc.paragraphs:
            rows.append(
                {
                    "kind": "uncited",
                    "subject": doc.name,
                    "document": doc.name,
                    "what": f"uncited: no feature was read from {doc.name}",
                    "advice": _ADVICE["uncited"].format(project=name, document=doc.name),
                }
            )
    return rows
